"""Physical and astronomical constants for Earth orbit simulation."""

MU: float = 398600.4418  # km^3/s^2, Earth standard gravitational parameter
R_EARTH: float = 6371.0  # km, Earth mean spherical radius
R_E: float = R_EARTH
OMEGA_E: float = 7.2921159e-5  # rad/s, Earth rotational angular velocity

# Physical and timing constants
C_KMS: float = 299792.458  # km/s, speed of light in vacuum
PROC_MS: float = 0.3  # ms, per-hop processing delay

# Constellation topology and link budget parameters
ATMOS_KM: float = 80.0  # km, Earth atmospheric occlusion height for line-of-sight
ISL_MAX_RANGE_KM: float = 5000.0  # km, maximum inter-satellite link range
ISL_MAX_DEGREE: int = 4  # maximum ISL transceivers per satellite
ISL_BUILD_FRAC: float = 0.92  # fraction of max range at which ISL links are built
GSL_EL_MIN_DEG: float = 10.0  # degrees, minimum elevation angle for ground-satellite link
GSL_DROP_MARGIN_DEG: float = 2.0  # degrees, margin below el_min before dropping link
GSL_MAX_PER_STATION: int = 3  # maximum simultaneous GSL connections per ground station
