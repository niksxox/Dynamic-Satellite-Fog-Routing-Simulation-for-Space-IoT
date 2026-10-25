"""Discrete-event packet forwarding, topology changes, and route recovery.

The engine is headless and owns one SimPy virtual-time environment. Packet
forwarding is hop-by-hop. A transmission already being serialized completes
and propagates if the link fails; queued packets re-check the link after
acquiring its resource, and all later hops use the current graph. Links are
full duplex by default (independent per-direction resources); set
``half_duplex_links`` to make both directions share one resource.
"""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from typing import Generator

import simpy

from src.metrics.collector import summarize
from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Packet, PacketState
from src.routing import RoutingEngine, RoutingMode
from src.simulation.events import FailureSchedule, RoutingDecision, SimulationEvent
from src.simulation.results import SimulationResults
from src.topology.engine import TopologyEngine
from src.traffic.generator import TrafficSpec, generator_process

logger = logging.getLogger(__name__)
BITS_PER_BYTE = 8
BITS_PER_MEGABIT = 1_000_000.0


def transmission_delay_s(packet_size_bytes: int, bandwidth_mbps: float) -> float:
    """Serialize a packet in seconds from bytes and decimal megabits/second."""
    if packet_size_bytes <= 0:
        raise ValueError("packet_size_bytes must be positive")
    if bandwidth_mbps <= 0:
        raise ValueError("bandwidth_mbps must be positive")
    return packet_size_bytes * BITS_PER_BYTE / (bandwidth_mbps * BITS_PER_MEGABIT)


class SimulationEngine:
    """Run one reproducible SimPy simulation over a topology and router.

    Construct with node models, one or more ``TrafficSpec`` objects, and an
    optional deterministic failure schedule. Call ``run()`` once and inspect
    its structured ``SimulationResults``. Packets still active at the horizon
    are marked ``PENDING`` (right-censored), not delivered, dropped, or assigned
    a fabricated latency. PDR uses all generated packets as its denominator.
    """

    def __init__(
        self,
        config: SimulationConfig,
        nodes: list[Node],
        traffic: list[TrafficSpec] | None = None,
        *,
        routing_mode: RoutingMode | str = RoutingMode.SHORTEST_LATENCY,
        failures: list[FailureSchedule] | None = None,
        run_id: str = "run-1",
        topology: TopologyEngine | None = None,
        router: RoutingEngine | None = None,
    ) -> None:
        self.config = config
        self.nodes = {node.node_id: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("node IDs must be unique")
        if not self.nodes:
            raise ValueError("at least one node is required")
        if traffic is None:
            traffic = [
                TrafficSpec(
                    source=node.node_id,
                    destination=node.destination or "",
                    rate_pps=node.packet_generation_rate_pps,
                    packet_size_bytes=node.default_packet_size_bytes,
                    priority=node.traffic_priority,
                )
                for node in nodes
                if node.node_type is NodeType.IOT
                and node.destination is not None
                and node.packet_generation_rate_pps > 0
            ]
        self.traffic = list(traffic)
        self.failures = sorted(failures or [], key=lambda f: f.time_s)
        self.routing_mode = RoutingMode(routing_mode)
        self.run_id = run_id
        self.topology = topology or TopologyEngine(config)
        self.router = router or RoutingEngine(config)
        for spec in self.traffic:
            if spec.source not in self.nodes or spec.destination not in self.nodes:
                raise ValueError(f"unknown traffic endpoint: {spec.source!r}->{spec.destination!r}")
            if self.nodes[spec.source].node_type is not NodeType.IOT:
                raise ValueError("traffic source must be an IoT node")
        for failure in self.failures:
            if failure.time_s > config.duration_s:
                raise ValueError("failure event occurs after simulation duration")
            if failure.node_id is not None and failure.node_id not in self.nodes:
                raise ValueError(f"unknown failure node: {failure.node_id}")
            for endpoint in (failure.source, failure.target):
                if endpoint is not None and endpoint not in self.nodes:
                    raise ValueError(f"unknown failure link endpoint: {endpoint}")
            if failure.event_type in {"fog_overload", "fog_recovery"} and (
                self.nodes[failure.node_id].node_type is not NodeType.FOG
            ):
                raise ValueError(f"{failure.event_type} requires a fog node")
        self.env: simpy.Environment | None = None
        self.results: SimulationResults | None = None
        self._ran = False
        self._packets: list[Packet] = []
        self._packet_sequence = 0
        self._event_sequence = 0
        self._events_truncated = False
        self._events: list[SimulationEvent] = []
        self._decisions: list[RoutingDecision] = []
        self._link_resources: dict[tuple[object, ...], simpy.Resource] = {}
        self._fog_resources: dict[str, simpy.Resource] = {}
        self._rng = random.Random(config.seed)
        self._link_stats: dict[str, dict[str, float]] = defaultdict(
            lambda: {"transmissions": 0, "delivered_frames": 0, "lost_frames": 0,
                     "bytes": 0, "serialization_s": 0.0}
        )
        self._fog_stats: dict[str, dict[str, float]] = defaultdict(
            lambda: {"packets": 0, "queue_wait_s": 0.0, "service_s": 0.0,
                     "busy_s": 0.0, "servers": 0.0}
        )
        self._recovery_times: list[float] = []
        self._recovery_failures = 0
        self._topology_event_cursor = 0

    def run(self, duration_s: float | None = None) -> SimulationResults:
        """Initialize and run to a fixed horizon using virtual time only."""
        if self._ran:
            raise RuntimeError("SimulationEngine instances can only be run once")
        duration = self.config.duration_s if duration_s is None else duration_s
        if duration <= 0:
            raise ValueError("duration_s must be positive")
        if duration / self.config.topology_update_interval_s > self.config.max_event_records:
            raise ValueError("topology update count exceeds configured event safety limit")
        self._ran = True
        wall_start = time.perf_counter()
        self.env = simpy.Environment()
        self.topology.initialize_network(list(self.nodes.values()), time_s=0.0)
        for event in self.topology.events:
            self._record_topology_event(event)
        self._topology_event_cursor = len(self.topology.events)
        self.env.process(self._topology_process(duration))
        for failure in self.failures:
            self.env.process(self._failure_process(failure))
        for index, spec in enumerate(self.traffic):
            stream = random.Random(self.config.seed + index * 1_000_003)
            self.env.process(generator_process(self.env, spec, stream, duration, self._create_packet))
        self.env.run(until=duration)

        # The observation window ends at the configured horizon. Active
        # packets are censored observations and retain their last known path.
        for packet in self._packets:
            if packet.state not in {
                PacketState.DELIVERED, PacketState.DROPPED, PacketState.TIMED_OUT,
                PacketState.PENDING,
            }:
                packet.state = PacketState.PENDING
                packet.drop_reason = "simulation horizon reached while packet was active"
                self._record("packet_pending", affected_node=packet.current_location,
                             packet_id=packet.packet_id,
                             description="Packet censored at simulation horizon")
        metrics = summarize(
            self._packets, duration, self._recovery_times, self._recovery_failures
        )
        self.results = SimulationResults(
            run_id=self.run_id,
            config=self.config,
            routing_mode=self.routing_mode.value,
            start_time_s=0.0,
            end_time_s=duration,
            wall_clock_runtime_s=time.perf_counter() - wall_start,
            packets=self._packets,
            events=self._events,
            routing_decisions=self._decisions,
            route_recovery_times_s=self._recovery_times,
            route_recovery_failures=self._recovery_failures,
            link_statistics={k: dict(v) for k, v in self._link_stats.items()},
            fog_statistics=self._final_fog_statistics(duration),
            topology_statistics=self.topology.topology_statistics(),
            per_node_statistics=self._final_node_statistics(),
            events_truncated=self._events_truncated,
            metrics=metrics,
        )
        logger.info("simulation %s completed in %.3fs wall time", self.run_id,
                    time.perf_counter() - wall_start)
        return self.results

    def _create_packet(self, spec: TrafficSpec, timestamp: float) -> Packet | None:
        if len(self._packets) >= self.config.max_generated_packets:
            logger.warning("packet generation capped at %d", self.config.max_generated_packets)
            return None
        self._packet_sequence += 1
        packet = Packet(
            packet_id=f"{self.run_id}-pkt-{self._packet_sequence:08d}",
            source=spec.source,
            destination=spec.destination,
            size_bytes=spec.packet_size_bytes,
            generated_at_s=timestamp,
            state=PacketState.WAITING_FOR_ROUTE,
            path=[spec.source],
            priority=spec.priority,
        )
        self._packets.append(packet)
        assert self.env is not None
        self.env.process(self._forward_packet(packet))
        self._record("packet_generated", packet_id=packet.packet_id,
                     affected_node=packet.source,
                     description="IoT packet generated",
                     details={"destination": packet.destination,
                              "size_bytes": packet.size_bytes, "priority": spec.priority})
        return packet

    def _forward_packet(self, packet: Packet) -> Generator:
        assert self.env is not None
        deadline = packet.generated_at_s + self.config.packet_timeout_s
        attempts_without_route = 0
        active_route: list[str] | None = None
        route_index = 0

        while self.env.now < deadline and packet.state not in _TERMINAL:
            if active_route is None:
                route = self.router.route(
                    self.topology.graph, packet.current_location or packet.source,
                    packet.destination, self.routing_mode, packet_size_bytes=packet.size_bytes,
                )
                self._record_decision(packet, route, "initial" if attempts_without_route == 0 else "retry")
                if route.route_available and self._valid_path(route.path):
                    active_route = route.path
                    route_index = 0
                else:
                    attempts_without_route += 1
                    if attempts_without_route > self.config.max_packet_retries:
                        self._finish(packet, PacketState.DROPPED, "no available route after retry limit")
                        return
                    packet.state = PacketState.WAITING_FOR_ROUTE
                    if not (yield from self._wait_timeout(min(
                        self.config.topology_update_interval_s, deadline - self.env.now
                    ), deadline)):
                        break
                    continue

            current = packet.current_location or packet.source
            if current == packet.destination:
                self._finish(packet, PacketState.DELIVERED)
                return
            if route_index >= len(active_route) - 1 or active_route[route_index] != current:
                active_route = None
                continue

            next_node = active_route[route_index + 1]
            if not self._edge_available(current, next_node):
                recovery = yield from self._recover_route(packet, active_route, deadline)
                if recovery is None:
                    if packet.state in _TERMINAL:
                        return
                    self._finish(
                        packet,
                        PacketState.TIMED_OUT if self.env.now >= deadline else PacketState.DROPPED,
                        "packet timeout exceeded during route recovery"
                        if self.env.now >= deadline
                        else "no replacement route after bounded recovery attempts",
                    )
                    return
                active_route = recovery
                route_index = 0
                attempts_without_route = 0
                continue

            resource = self._link_resource(current, next_node)
            requested_at = float(self.env.now)
            request = resource.request()
            acquired = yield request | self.env.timeout(max(0.0, deadline - self.env.now))
            if request not in acquired:
                request.cancel()
                break
            resource_held = True
            try:
                # A packet queued for a failed link does not start a frame on it.
                if not self._edge_available(current, next_node):
                    old_route = active_route
                    resource.release(request)
                    resource_held = False
                    recovery = yield from self._recover_route(packet, old_route, deadline)
                    if recovery is None:
                        timed_out = self.env.now >= deadline
                        self._finish(packet,
                                     PacketState.TIMED_OUT if timed_out else PacketState.DROPPED,
                                     "packet timeout exceeded during route recovery"
                                     if timed_out else "no replacement route after queued-link failure")
                        return
                    active_route = recovery
                    route_index = 0
                    attempts_without_route = 0
                    continue
                packet.state = PacketState.IN_TRANSIT
                bandwidth = float(self.topology.graph.edges[current, next_node]["bandwidth_mbps"])
                tx_s = transmission_delay_s(packet.size_bytes, bandwidth)
                overhead_s = float(self.topology.graph.edges[current, next_node].get(
                    "transmission_overhead_ms", 0.0
                )) / 1000.0
                data = self.topology.graph.edges[current, next_node]
                key = _link_key(current, next_node)
                stats = self._link_stats[_display_link(current, next_node)]
                stats["transmissions"] += 1
                frame_time = tx_s + overhead_s
                if not (yield from self._wait_timeout(frame_time, deadline)):
                    break
                stats["serialization_s"] += tx_s
                stats["bytes"] += packet.size_bytes
                # The shared channel limits serialization. Propagation is in
                # flight after the channel becomes available for the next frame.
                resource.release(request)
                resource_held = False
                # Defined in-flight policy: once serialization starts, the
                # current frame completes its propagation even if the link is
                # taken down during serialization or flight.
                propagation_s = float(data.get("propagation_latency_ms", 0.0)) / 1000.0
                if not (yield from self._wait_timeout(propagation_s, deadline)):
                    break
                if not self.nodes[next_node].operational:
                    stats["lost_frames"] += 1
                    self._record("packet_loss", source=current, target=next_node,
                                 packet_id=packet.packet_id,
                                 description="Frame reached an unavailable receiving node")
                    self._finish(packet, PacketState.DROPPED,
                                 f"receiving node {next_node} failed in flight")
                    return
                if self._rng.random() < float(data.get("packet_loss_probability", 0.0)):
                    stats["lost_frames"] += 1
                    self._record("packet_loss", source=current, target=next_node,
                                 packet_id=packet.packet_id, description="Frame lost on link")
                    self._finish(packet, PacketState.DROPPED,
                                 f"packet loss on link {current}<->{next_node}")
                    return
                stats["delivered_frames"] += 1
                packet.current_location = next_node
                packet.path.append(next_node)
                packet.hop_count += 1
                route_index += 1
                self._record("packet_hop", source=current, target=next_node,
                             packet_id=packet.packet_id, description="Packet completed one hop",
                             details={"transmission_s": tx_s,
                                      "propagation_s": propagation_s,
                                      "link_key": key,
                                       "link_queue_wait_s": max(
                                           0.0, float(self.env.now - requested_at - frame_time - propagation_s)
                                       )})
            finally:
                if resource_held and request in resource.users:
                    resource.release(request)

            if self.nodes[next_node].node_type is NodeType.FOG:
                processed = yield from self._process_at_fog(packet, next_node, deadline)
                if not processed:
                    if packet.state in _TERMINAL:
                        return
                    # A failed fog node may recover later. Re-route from the
                    # current location after a bounded wait instead of serving
                    # a failed resource.
                    active_route = None
                    if not (yield from self._wait_timeout(min(
                        self.config.topology_update_interval_s, deadline - self.env.now
                    ), deadline)):
                        break
                    continue

        if packet.state not in _TERMINAL:
            self._finish(packet, PacketState.TIMED_OUT, "packet timeout exceeded")

    def _recover_route(
        self, packet: Packet, old_route: list[str], deadline: float
    ) -> Generator[None, None, list[str] | None]:
        assert self.env is not None
        detected = float(self.env.now)
        current = packet.current_location or packet.source
        self._record("route_invalidated", affected_node=current, packet_id=packet.packet_id,
                     description="Next hop unavailable at forwarding decision",
                     details={"old_route": list(old_route), "detected_at_s": detected})
        attempts = 0
        while attempts <= self.config.max_packet_retries and self.env.now < deadline:
            attempts += 1
            delay_s = self.config.route_computation_delay_ms / 1000.0
            if not (yield from self._wait_timeout(min(delay_s, deadline - self.env.now), deadline)):
                break
            route = self.router.route(
                self.topology.graph, current, packet.destination, self.routing_mode,
                packet_size_bytes=packet.size_bytes,
            )
            if route.route_available and self._valid_path(route.path):
                recovered_at = float(self.env.now)
                recovery_s = recovered_at - detected
                packet.reroute_count += 1
                self._recovery_times.append(recovery_s)
                self._record_decision(packet, route, "failure_recovery", detected, recovery_s)
                self._record("route_changed", affected_node=current, packet_id=packet.packet_id,
                             description="Selected valid replacement route",
                             details={"old_route": list(old_route),
                                      "new_route": list(route.path),
                                      "cause": "next_hop_unavailable",
                                      "failure_detected_s": detected,
                                      "route_selected_s": recovered_at,
                                      "recovery_time_s": recovery_s})
                return route.path
            self._record_decision(packet, route, "failure_recovery_failed", detected)
            if attempts <= self.config.max_packet_retries:
                wait_s = min(self.config.topology_update_interval_s, deadline - self.env.now)
                if wait_s <= 0 or not (yield from self._wait_timeout(wait_s, deadline)):
                    break
        self._recovery_failures += 1
        self._record("route_recovery_failed", affected_node=current, packet_id=packet.packet_id,
                     description="No valid replacement route before retry limit or timeout",
                     details={"old_route": list(old_route), "failure_detected_s": detected,
                              "attempts": attempts})
        return None

    def _process_at_fog(self, packet: Packet, fog_id: str, deadline: float) -> Generator:
        assert self.env is not None
        node = self.nodes[fog_id]
        if not node.operational:
            self._record("fog_unavailable", affected_node=fog_id, packet_id=packet.packet_id,
                         description="Fog node unavailable on arrival")
            return False
        resource = self._fog_resources.setdefault(
            fog_id, simpy.Resource(self.env, capacity=self.config.fog_default_servers)
        )
        queued_at = float(self.env.now)
        packet.state = PacketState.WAITING_FOR_FOG
        request = resource.request()
        acquired = yield request | self.env.timeout(max(0.0, deadline - self.env.now))
        if request not in acquired:
            request.cancel()
            return False
        try:
            if not node.operational:
                return False
            service_s = max(
                node.processing_delay_ms / 1000.0,
                1.0 / node.processing_capacity_pps if node.processing_capacity_pps else 0.0,
            )
            stats = self._fog_stats[fog_id]
            stats["packets"] += 1
            stats["queue_wait_s"] += max(0.0, float(self.env.now) - queued_at)
            stats["servers"] = float(self.config.fog_default_servers)
            service_started = float(self.env.now)
            completed = yield from self._wait_timeout(service_s, deadline)
            actual_service_s = float(self.env.now) - service_started
            stats["service_s"] += actual_service_s
            stats["busy_s"] += actual_service_s
            if not completed:
                return False
            packet.state = PacketState.IN_TRANSIT
            return True
        finally:
            if request in resource.users:
                resource.release(request)

    def _topology_process(self, duration_s: float) -> Generator:
        assert self.env is not None
        interval = self.config.topology_update_interval_s
        while self.env.now + interval <= duration_s:
            yield self.env.timeout(interval)
            self.topology.update_topology(float(self.env.now))
            self._sync_topology_events()

    def _failure_process(self, failure: FailureSchedule) -> Generator:
        assert self.env is not None
        delay = max(0.0, failure.time_s - self.env.now)
        yield self.env.timeout(delay)
        event_type = failure.event_type
        if event_type in {"link_failure", "link_recovery"}:
            if event_type == "link_failure" and not self.topology.graph.has_edge(
                failure.source or "", failure.target or ""
            ):
                raise ValueError("cannot fail a link that is not physically eligible")
            self.topology.set_link_operational(
                failure.source or "", failure.target or "",
                event_type == "link_recovery", float(self.env.now),
            )
            self._sync_topology_events()
            affected = f"{failure.source}<->{failure.target}"
        elif event_type in {"node_failure", "node_recovery", "fog_overload", "fog_recovery"}:
            node_id = failure.node_id or ""
            if node_id not in self.nodes:
                raise ValueError(f"unknown failure node: {node_id}")
            if event_type in {"fog_overload", "fog_recovery"} and self.nodes[node_id].node_type is not NodeType.FOG:
                raise ValueError(f"{event_type} requires a fog node")
            operational = event_type in {"node_recovery", "fog_recovery"}
            self.topology.set_node_operational(node_id, operational, float(self.env.now))
            self._sync_topology_events()
            affected = node_id
        else:  # link quality changes
            self.topology.set_link_conditions(
                failure.source or "", failure.target or "", float(self.env.now),
                congestion=failure.value if event_type == "congestion_change" else None,
                packet_loss_probability=(failure.value
                                         if event_type == "packet_loss_change" else None),
            )
            self._sync_topology_events()
            affected = f"{failure.source}<->{failure.target}"
        self._record(event_type, affected_node=failure.node_id,
                     source=failure.source, target=failure.target,
                     description=failure.description or f"Applied {event_type}",
                     details={"affected_resource": affected, "value": failure.value})

    def _link_resource(self, source: str, target: str) -> simpy.Resource:
        assert self.env is not None
        if self.config.half_duplex_links:
            key: tuple[object, ...] = ("shared", *_link_key(source, target))
        else:
            key = ("direction", source, target)
        if key not in self._link_resources:
            self._link_resources[key] = simpy.Resource(self.env, capacity=1)
        return self._link_resources[key]

    def _edge_available(self, source: str, target: str) -> bool:
        graph = self.topology.graph
        return (
            source in graph and target in graph
            and bool(graph.nodes[source].get("operational", True))
            and bool(graph.nodes[target].get("operational", True))
            and graph.has_edge(source, target)
            and bool(graph.edges[source, target].get("operational", True))
        )

    def _valid_path(self, path: list[str]) -> bool:
        return bool(path) and all(self._edge_available(a, b) for a, b in zip(path, path[1:]))

    def _wait_timeout(self, delay_s: float, deadline: float) -> Generator[None, None, bool]:
        assert self.env is not None
        remaining = deadline - self.env.now
        if remaining <= 0:
            return False
        duration = min(max(0.0, delay_s), remaining)
        yield self.env.timeout(duration)
        return self.env.now < deadline or duration < remaining

    def _finish(self, packet: Packet, state: PacketState, reason: str | None = None) -> None:
        if packet.state in _TERMINAL:
            return
        assert self.env is not None
        packet.state = state
        if state is PacketState.DELIVERED:
            packet.delivered_at_s = float(self.env.now)
            packet.latency_s = packet.delivered_at_s - packet.generated_at_s
            packet.drop_reason = None
            self._record("packet_delivered", affected_node=packet.destination,
                         packet_id=packet.packet_id, description="Packet delivered",
                         details={"latency_s": packet.latency_s,
                                  "hop_count": packet.hop_count})
        else:
            packet.drop_reason = reason
            self._record("packet_dropped" if state is PacketState.DROPPED else "packet_timed_out",
                         affected_node=packet.current_location, packet_id=packet.packet_id,
                         description=reason or state.value)

    def _record_decision(self, packet: Packet, route, cause: str,
                         detected: float | None = None,
                         recovery_s: float | None = None) -> None:
        timestamp = float(self.env.now) if self.env is not None else 0.0
        decision = RoutingDecision(
            timestamp_s=timestamp,
            packet_id=packet.packet_id,
            algorithm=route.algorithm,
            source=route.source,
            destination=route.destination,
            path=tuple(route.path),
            available=route.route_available,
            cause=cause,
            route_cost=route.total_cost,
            estimated_latency_ms=route.estimated_latency_ms,
            failure_detection_s=detected,
            recovery_time_s=recovery_s,
        )
        if len(self._decisions) < self.config.max_event_records:
            self._decisions.append(decision)
        else:
            self._events_truncated = True
        self._record("route_computed", affected_node=route.source,
                     packet_id=packet.packet_id, description=f"Routing decision: {cause}",
                     details={"algorithm": route.algorithm, "path": list(route.path),
                              "available": route.route_available, "cause": cause,
                              "route_cost": route.total_cost,
                              "estimated_latency_ms": route.estimated_latency_ms})

    def _record(self, event_type: str, *, affected_node: str | None = None,
                source: str | None = None, target: str | None = None,
                packet_id: str | None = None, description: str = "",
                details: dict[str, object] | None = None) -> None:
        assert self.env is not None
        if len(self._events) >= self.config.max_event_records:
            self._events_truncated = True
            return
        self._event_sequence += 1
        self._events.append(SimulationEvent(
            event_id=f"{self.run_id}-evt-{self._event_sequence:08d}",
            timestamp_s=float(self.env.now), event_type=event_type,
            affected_node=affected_node, source=source, target=target,
            packet_id=packet_id, description=description,
            details=details or {},
        ))

    def _record_topology_event(self, event) -> None:
        self._record(event.event_type, source=event.source, target=event.target,
                     description=f"Topology {event.event_type}")

    def _sync_topology_events(self) -> None:
        # Events are copied once into the structured run log.
        new = self.topology.events[self._topology_event_cursor:]
        self._topology_event_cursor = len(self.topology.events)
        for event in new:
            self._record_topology_event(event)

    def _final_fog_statistics(self, duration_s: float) -> dict[str, dict[str, float]]:
        output: dict[str, dict[str, float]] = {}
        for node_id, node in self.nodes.items():
            if node.node_type is not NodeType.FOG:
                continue
            stats = dict(self._fog_stats[node_id])
            servers = max(stats["servers"], 1.0)
            stats["utilization"] = min(1.0, stats["busy_s"] / (duration_s * servers))
            stats["mean_queue_wait_s"] = (
                stats["queue_wait_s"] / stats["packets"] if stats["packets"] else 0.0
            )
            output[node_id] = stats
        return output

    def _final_node_statistics(self) -> dict[str, dict[str, float]]:
        """Return packet source and observed transit counts for every node."""
        counts = {
            node_id: {"packets_generated": 0.0, "packets_seen": 0.0,
                      "packets_delivered_as_destination": 0.0}
            for node_id in self.nodes
        }
        for packet in self._packets:
            counts[packet.source]["packets_generated"] += 1
            for node_id in set(packet.path):
                if node_id in counts:
                    counts[node_id]["packets_seen"] += 1
            if packet.state is PacketState.DELIVERED:
                counts[packet.destination]["packets_delivered_as_destination"] += 1
        return counts


_TERMINAL = {
    PacketState.DELIVERED, PacketState.DROPPED, PacketState.TIMED_OUT,
    PacketState.PENDING,
}


def _link_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def _display_link(source: str, target: str) -> str:
    return f"{min(source, target)}<->{max(source, target)}"
