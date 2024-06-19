# ruff: noqa: F405,F403
# pyright: reportReturnType=none
# pyright: reportAssignmentType=none
"""
The calculations in this module are based on the MetPy library. These calculations supplement
the original implementation in areas where previously only support for `1D profiles
(not higher-dimension vertical cross sections or grids)`.
"""

from __future__ import annotations

from typing import Any, Final, Literal as L, TypeVar

import numpy as np
from numpy.typing import ArrayLike, NDArray

from . import functional as F
from ._core import moist_lapse, parcel_profile_with_lcl
from ._ufunc import (
    dewpoint as _dewpoint,
    dry_lapse,
    equivalent_potential_temperature,
    greater_or_close,
    lcl,
    lcl_pressure,
    mixing_ratio,
    pressure_vector,
    saturation_mixing_ratio,
    saturation_vapor_pressure,
    vapor_pressure,
    virtual_temperature,
    wet_bulb_temperature,
)
from .const import Rd
from .typing import Kelvin, N, Pascal, Z, shape
from .utils import Axis, Vector1d, broadcast_nz

_S = TypeVar("_S", bound=shape)
_T = TypeVar("_T", bound=np.floating[Any], covariant=True)
newaxis: Final[None] = np.newaxis
surface: Final[tuple[slice, slice]] = np.s_[:, :1]
aloft: Final[tuple[slice, slice]] = np.s_[:, 1:]
NaN = np.nan


FASTPATH: dict[str, Any] = {"__fastpath": True}


def parcel_mixing_ratio(
    pressure: Pascal[pressure_vector[_S, np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[_S, np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[_S, np.dtype[_T]]],
    /,
    *,
    where: np.ndarray[_S, np.dtype[np.bool_]] | None = None,
) -> np.ndarray[_S, np.dtype[_T]]:
    if where is None:
        where = pressure.is_below(
            lcl_pressure(pressure[surface], temperature[surface], dewpoint[surface])
        )
    r = saturation_mixing_ratio(pressure, dewpoint, out=np.empty_like(temperature), where=where)
    r = saturation_mixing_ratio(pressure, temperature, out=r, where=~where)
    return r


# -------------------------------------------------------------------------------------------------
# downdraft_cape
# -------------------------------------------------------------------------------------------------
@broadcast_nz
def downdraft_cape(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    where: np.ndarray[shape[N, Z], np.dtype[np.bool_]] | None = None,
) -> np.ndarray[shape[N], np.dtype[_T]]:
    """Calculate downward CAPE (DCAPE).

    Calculate the downward convective available potential energy (DCAPE) of a given upper air
    profile. Downward CAPE is the maximum negative buoyancy energy available to a descending
    parcel. Parcel descent is assumed to begin from the lowest equivalent potential temperature
    between 700 and 500 hPa. This parcel is lowered moist adiabatically from the environmental
    wet bulb temperature to the surface.  This assumes the parcel remains saturated
    throughout the descent.

    Parameters
    ----------
    TODO: add parameters

    Examples
    --------
    TODO: add examples

    """
    N, _ = temperature.shape
    nx = np.arange(N)
    # Tims suggestion was to allow for the parcel to potentially be conditionally based
    if where is None:
        where = (pressure <= 70000.0) & (pressure >= 50000.0)

    theta_e = equivalent_potential_temperature(
        pressure,
        temperature,
        dewpoint,
        # masking values with inf will alow us to call argmin without worrying about nan
        where=where,
        out=np.full_like(temperature, np.inf),
    )
    zx = theta_e.argmin(axis=1)

    p_top = pressure[nx, zx] if pressure.shape == temperature.shape else pressure[0, zx]
    t_top = temperature[nx, zx]  # (N,)
    td_top = dewpoint[nx, zx]  # (N,)
    wb_top = wet_bulb_temperature(p_top, t_top, td_top)  # (N,)

    # our moist_lapse rate function has nan ignoring capabilities
    # pressure = pressure.where(pressure >= p_top[:, newaxis], NaN)
    pressure = pressure.where(pressure.is_below(p_top[:, newaxis], close=True), NaN)
    e_vt = virtual_temperature(temperature, saturation_mixing_ratio(pressure, dewpoint))  # (N, Z)
    trace = moist_lapse(pressure, wb_top, p_top)  # (N, Z)
    p_vt = virtual_temperature(trace, saturation_mixing_ratio(pressure, trace))  # (N, Z)

    DCAPE = Rd * F.nantrapz(p_vt - e_vt, np.log(pressure), axis=1)

    return DCAPE


# -------------------------------------------------------------------------------------------------
# convective condensation level
# -------------------------------------------------------------------------------------------------
@broadcast_nz
def ccl(
    pressure: Pascal[NDArray[_T]],
    temperature: Kelvin[NDArray[_T]],
    dewpoint: Kelvin[NDArray[_T]],
    /,
    *,
    height=None,
    mixed_layer_depth=None,
    which: L["bottom", "top"] = "bottom",
):
    """
    # Convective Condensation Level (CCL)

    The Convective Condensation Level (CCL) is the level at which condensation will occur if
    sufficient afternoon heating causes rising parcels of air to reach saturation. The CCL is
    greater than or equal in height (lower or equal pressure level) than the LCL. The CCL and the
    LCL are equal when the atmosphere is saturated. The CCL is found at the intersection of the
    saturation mixing ratio line (through the surface dewpoint) and the environmental temperature.
    """

    if mixed_layer_depth is None:
        r = mixing_ratio(saturation_vapor_pressure(dewpoint[surface]), pressure[surface])
    else:
        raise NotImplementedError
    if height is not None:
        raise NotImplementedError

    rt_profile = _dewpoint(vapor_pressure(pressure, r))

    p, t = F.intersect_nz(pressure, rt_profile, temperature, "increasing", log_x=True).pick(which)

    return p, t, dry_lapse(pressure[:, 0], t, p)


# -------------------------------------------------------------------------------------------------
# el & lfc
# -------------------------------------------------------------------------------------------------
def _el_lfc(
    pick: L["EL", "LFC", "BOTH"],
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    parcel_profile: Kelvin[np.ndarray[shape[N, Z], np.dtype[np.floating[Any]]]] | None = None,
    which_lfc: L["bottom", "top"] = "bottom",
    which_el: L["bottom", "top"] = "top",
    dewpoint_start: np.ndarray[shape[N], np.dtype[_T]] | None = None,
) -> tuple[Vector1d[_T], Vector1d[_T]] | Vector1d[_T]:
    if parcel_profile is None:
        pressure, temperature, dewpoint, parcel_profile = parcel_profile_with_lcl(
            pressure, temperature, dewpoint
        )

    N = temperature.shape[0]
    p0, t0 = pressure[:, 0], temperature[:, 0]
    if dewpoint_start is None:
        td0 = dewpoint[:, 0]  # (N,)
    else:
        td0 = dewpoint_start

    LCL = Vector1d.from_func(lcl, p0, t0, td0).unsqueeze()

    pressure, parcel_profile, temperature = (
        pressure[aloft],
        parcel_profile[aloft],
        temperature[aloft],
    )

    if pick != "LFC":  # find the Equilibrium Level (EL)
        top_idx = np.arange(N), np.argmin(~np.isnan(pressure), Axis.Z) - 1
        left_of_env = (parcel_profile[top_idx] <= temperature[top_idx])[:, newaxis]
        EL = F.intersect_nz(
            pressure,
            parcel_profile,
            temperature,
            "decreasing",
            log_x=True,
        ).where(
            # If the top of the sounding parcel is warmer than the environment, there is no EL
            lambda el: el.is_above(LCL) & left_of_env
        )

        if pick == "EL":
            return EL.pick(which_el)

    LFC = F.intersect_nz(
        pressure,
        parcel_profile,
        temperature,
        "increasing",
        log_x=True,
    ).where_above(LCL)

    no_lfc = LFC.is_nan().all(Axis.Z, out=np.empty((N, 1), dtype=np.bool_), keepdims=True)

    is_lcl = no_lfc & greater_or_close(
        # the mask only needs to be applied to either the temperature or parcel_temperature_profile
        np.where(LCL.is_below(pressure, close=True), parcel_profile, NaN),
        temperature,
    ).any(Axis.Z, out=np.empty((N, 1), dtype=np.bool_), keepdims=True)

    LFC = LFC.select(
        [~no_lfc, is_lcl],
        [LFC.pressure, LCL.pressure],
        [LFC.temperature, LCL.temperature],
    )

    if pick == "LFC":
        return LFC.pick(which_lfc)

    return EL.pick(which_el), LFC.pick(which_lfc)


@broadcast_nz
def el(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    parcel_profile: Kelvin[np.ndarray[shape[N, Z], np.dtype[np.floating[Any]]]] | None = None,
    *,
    which: L["top", "bottom"] = "top",
) -> Vector1d[_T]:
    return _el_lfc("EL", pressure, temperature, dewpoint, parcel_profile, which_el=which)


@broadcast_nz
def lfc(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    parcel_profile: np.ndarray | None = None,
    *,
    which: L["top", "bottom"] = "top",
    dewpoint_start: np.ndarray[shape[N], np.dtype[_T]] | None = None,
) -> Vector1d[_T]:
    return _el_lfc(
        "LFC",
        pressure,
        temperature,
        dewpoint,
        parcel_profile,
        which_lfc=which,
        dewpoint_start=dewpoint_start,
    )


@broadcast_nz
def el_lfc(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    parcel_profile: Kelvin[np.ndarray[shape[N, Z], np.dtype[np.floating[Any]]]] | None = None,
    *,
    which_lfc: L["bottom", "top"] = "bottom",
    which_el: L["bottom", "top"] = "top",
    dewpoint_start: np.ndarray[shape[N], np.dtype[_T]] | None = None,
) -> tuple[Vector1d[_T], Vector1d[_T]]:
    return _el_lfc(
        "BOTH",
        pressure,
        temperature,
        dewpoint,
        parcel_profile,
        which_lfc=which_lfc,
        which_el=which_el,
        dewpoint_start=dewpoint_start,
    )


# -------------------------------------------------------------------------------------------------
# nzthermo.core.most_unstable_parcel
# -------------------------------------------------------------------------------------------------
@broadcast_nz
def most_unstable_parcel_index(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    depth: float = 30000.0,
    height: float | None = None,
    bottom: float | None = None,
) -> np.ndarray[shape[N], np.dtype[np.intp]]:
    if height is not None:
        raise NotImplementedError("height argument is not implemented")

    pbot = (pressure[surface] if bottom is None else np.asarray(bottom)).reshape(-1, 1)
    ptop = pbot - depth

    theta_e = equivalent_potential_temperature(
        pressure,
        temperature,
        dewpoint,
        where=pressure.is_between(pbot, ptop),
        out=np.full(temperature.shape, -np.inf, dtype=temperature.dtype),
    )

    return np.argmax(theta_e, axis=1)


@broadcast_nz
def most_unstable_parcel(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    *,
    depth: Pascal[float] = 30000.0,
    bottom: Pascal[float] | None = None,
) -> tuple[
    Pascal[np.ndarray[shape[N], np.dtype[_T]]],
    Kelvin[np.ndarray[shape[N], np.dtype[_T]]],
    Kelvin[np.ndarray[shape[N], np.dtype[_T]]],
    np.ndarray[shape[N, Z], np.dtype[np.intp]],
]:
    idx = most_unstable_parcel_index(
        pressure, temperature, dewpoint, depth=depth, bottom=bottom, **FASTPATH
    )

    return (
        pressure[np.arange(pressure.shape[0]), idx],
        temperature[np.arange(temperature.shape[0]), idx],
        dewpoint[np.arange(dewpoint.shape[0]), idx],
        idx,
    )


# -------------------------------------------------------------------------------------------------
# nzthermo.core.mixed_layer
# -------------------------------------------------------------------------------------------------
@broadcast_nz
def mixed_layer(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    *,
    depth: float | NDArray[np.floating[Any]] = 10000.0,
    height: ArrayLike | None = None,
    bottom: ArrayLike | None = None,
    interpolate=False,
) -> tuple[
    np.ndarray[shape[N], np.dtype[_T]],
    Kelvin[np.ndarray[shape[N], np.dtype[_T]]],
]:
    if height is not None:
        raise NotImplementedError("height argument is not implemented")
    if interpolate:
        raise NotImplementedError("interpolate argument is not implemented")

    bottom = (pressure[surface] if bottom is None else np.asarray(bottom)).reshape(-1, 1)
    top = bottom - depth

    where = pressure.is_between(bottom, top)

    depth = np.asarray(
        # use asarray otherwise the depth is cast to pressure_vector which doesn't
        # make sense for the temperature and dewpoint outputs
        np.max(pressure, initial=-np.inf, axis=1, where=where)
        - np.min(pressure, initial=np.inf, axis=1, where=where)
    )

    T, Td = F.nantrapz([temperature, dewpoint], pressure, axis=-1, where=where) / -depth

    return T, Td


# -------------------------------------------------------------------------------------------------
# cape_cin
# -------------------------------------------------------------------------------------------------
@broadcast_nz
def cape_cin(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    parcel_profile: np.ndarray,
    *,
    which_lfc: L["bottom", "top"] = "bottom",
    which_el: L["bottom", "top"] = "top",
) -> tuple[np.ndarray, np.ndarray]:
    # The mixing ratio of the parcel comes from the dewpoint below the LCL, is saturated
    # based on the temperature above the LCL

    parcel_profile = virtual_temperature(
        parcel_profile, parcel_mixing_ratio(pressure, temperature, dewpoint)
    )
    temperature = virtual_temperature(temperature, saturation_mixing_ratio(pressure, dewpoint))
    # Calculate the EL limit of integration
    (EL, _), (LFC, _) = _el_lfc(
        "BOTH",
        pressure,
        temperature,
        dewpoint,
        parcel_profile,
        which_lfc,
        which_el,
    )
    EL, LFC = np.reshape((EL, LFC), (2, -1, 1))  # reshape for broadcasting

    tzx = F.zero_crossings(pressure, parcel_profile - temperature)  # temperature zero crossings

    p, t = tzx.where_between(LFC, EL, close=True)
    CAPE = Rd * F.nantrapz(t, np.log(p), axis=1)
    CAPE[CAPE < 0.0] = 0.0

    p, t = tzx.where_below(LFC, close=True)
    CIN = Rd * F.nantrapz(t, np.log(p), axis=1)
    CIN[CIN > 0.0] = 0.0

    return CAPE, CIN


@broadcast_nz
def most_unstable_cape_cin(
    pressure: Pascal[pressure_vector[shape[N, Z], np.dtype[_T]]],
    temperature: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    dewpoint: Kelvin[np.ndarray[shape[N, Z], np.dtype[_T]]],
    /,
    *,
    depth: Pascal[float] = 30000.0,
    bottom: Pascal[float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    idx = most_unstable_parcel_index(
        pressure,
        temperature,
        dewpoint,
        depth,
        bottom,
        **FASTPATH,
    )
    mask = np.arange(pressure.shape[1]) >= idx[:, newaxis]

    p, t, td, mu_profile = parcel_profile_with_lcl(
        pressure,
        temperature,
        dewpoint,
        where=mask,
    )

    return cape_cin(p.view(pressure_vector), t, td, parcel_profile=mu_profile, **FASTPATH)
