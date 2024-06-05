"""
This module wraps many of the c++ templated functions as `numpy.ufuncs`, so that they can be used
in a vectorized manner.

TDOD: rather than maintaing the external stub file a better use case would to set up a simple script
that generates the stub file from the c++ header file.
"""

# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True

# pyright: reportGeneralTypeIssues=false

cimport cython
cimport numpy as np

cimport nzthermo._C as C

ctypedef fused T:
    float
    double

ctypedef fused integer:
    short
    long


np.import_array()
np.import_ufunc()

# ............................................................................................... #
#  - wind
# ............................................................................................... #
@cython.ufunc
cdef T wind_direction(T u, T v) noexcept nogil:
    return C.wind_direction(u, v)

@cython.ufunc
cdef T wind_magnitude(T u, T v) noexcept nogil:
    return C.wind_magnitude(u, v)

@cython.ufunc
cdef (double, double) wind_components(T direction, T magnitude) noexcept nogil:
    # TODO: the signature....
    # cdef (T, T) wind_components(T direction, T magnitude) noexcept nogil:...
    # 
    # Is unsupported by the ufunc signature. So the option are:
    # - maintain gil
    # - cast to double 
    # - write the template in C
    cdef C.WindComponents[T] wnd = C.wind_components(direction, magnitude)
    return <double>wnd.u, <double>wnd.v

# ............................................................................................... #
#  - thermodynamic functions
# ............................................................................................... #
@cython.ufunc
cdef T saturation_vapor_pressure(T temperature) noexcept nogil:
    return C.saturation_vapor_pressure(temperature)

@cython.ufunc
cdef T virtual_temperature(T temperature, T mixing_ratio) noexcept nogil:
    return C.virtual_temperature(temperature, mixing_ratio)

@cython.ufunc
cdef T saturation_mixing_ratio(T pressure, T temperature) noexcept nogil:
    return C.saturation_mixing_ratio(pressure, temperature)

@cython.ufunc
cdef T dewpoint(T vapor_pressure) noexcept nogil:
    return C.dewpoint(vapor_pressure)

@cython.ufunc # theta
cdef T dry_lapse(T pressure, T temperature, T reference_pressure) noexcept nogil:
    return C.dry_lapse(pressure, reference_pressure, temperature)

@cython.ufunc # theta
cdef T potential_temperature(T pressure, T temperature) noexcept nogil:
    return C.potential_temperature(pressure, temperature)

@cython.ufunc # theta_e
cdef T equivalent_potential_temperature(T pressure, T temperature, T dewpoint) noexcept nogil:
    return C.equivalent_potential_temperature(pressure, temperature, dewpoint)

@cython.ufunc # theta_w
cdef T wet_bulb_potential_temperature(T pressure, T temperature, T dewpoint) noexcept nogil:
    return C.wet_bulb_potential_temperature(pressure, temperature, dewpoint)

@cython.ufunc 
cdef T wet_bulb_temperature(T pressure, T temperature, T dewpoint) noexcept nogil:
    cdef: # the ufunc signature doesn't support keyword arguments
        size_t max_iter = 50
        T eps  = 0.1
        T step = 1000.0

    return C.wet_bulb_temperature(pressure, temperature, dewpoint, eps, step, max_iter)


@cython.ufunc 
cdef T lcl_pressure(T pressure, T temperature, T dewpoint) noexcept nogil:
    cdef:
        size_t max_iter = 50
        T eps = 0.1

    return C.lcl_pressure(pressure, temperature, dewpoint, eps, max_iter)

@cython.ufunc
cdef (double, double) lcl(T pressure, T temperature, T dewpoint) noexcept nogil:
    # TODO: the signature....
    # cdef (T, T) lcl(T pressure, T temperature, T dewpoint) noexcept nogil:...
    # 
    # Is unsupported by the ufunc signature. So the option are:
    # - maintain gil
    # - cast to double 
    # - write the template in C
    cdef:
        size_t max_iter = 50
        T eps = 0.1
        C.LCL[T] lcl = C.lcl(pressure, temperature, dewpoint, eps, max_iter)

    return <double>lcl.pressure, <double>lcl.temperature


@cython.ufunc
cdef T wobus(T temperature) noexcept nogil:
    r"""
    /**
 * \author John Hart - NSSFC KCMO / NWSSPC OUN
 *
 * \brief Computes the difference between the wet-bulb potential<!--
 * --> temperatures for saturated and dry air given the temperature.
 *
 * The Wobus Function (wobf) is defined as the difference between
 * the wet-bulb potential temperature for saturated air (WBPTS)
 * and the wet-bulb potential temperature for dry air (WBPTD) given
 * the same temperature in Celsius.
 *
 * WOBF(T) := WBPTS - WBPTD
 *
 * Although WBPTS and WBPTD are functions of both pressure and
 * temperature, it is assumed their difference is a function of
 * temperature only. The difference is also proportional to the
 * heat imparted to a parcel.
 *
 * This function uses a polynomial approximation to the wobus function,
 * fitted to values in Table 78 of PP.319-322 of the Smithsonian Meteorological
 * Tables by Roland List (6th Revised Edition). Herman Wobus, a mathematician
 * for the Navy Weather Research Facility in Norfolk, VA computed these
 * coefficients a very long time ago, as he was retired as of the time of
 * the documentation found on this routine written in 1981.
 *
 * It was shown by Robert Davies-Jones (2007) that the Wobus function has
 * a slight dependence on pressure, which results in errors of up to 1.2
 * degrees Kelvin in the temperature of a lifted parcel.
 *
 * \param   temperature     (degK)
 *
 * \return  wobf            (degK)
 */
    """
    return C.wobus(temperature)



# -------------------------------------------------------------------------------------------------
# time
# -------------------------------------------------------------------------------------------------
@cython.ufunc
cdef double delta_t(integer year, integer month) noexcept nogil:
    """
    POLYNOMIAL EXPRESSIONS FOR DELTA T (ΔT)
    see: https://eclipse.gsfc.nasa.gov/SEcat5/deltatpoly.html
    Using the ΔT values derived from the historical record and from direct observations
    (see: Table 1 and Table 2), a series of polynomial expressions have been created to simplify
    the evaluation of ΔT for any time during the interval -1999 to +3000.
    """
    cdef double y, u, delta_t
    y = year + (month - 0.5) / 12

    if year < -500:
        u = (y - 1820) / 100
        delta_t = -20 + 32 * u**2
    elif year < 500:
        u = y / 100
        delta_t = (
            10583.6
            - 1014.41 * u
            + 33.78311 * u**2
            - 5.952053 * u**3
            - 0.1798452 * u**4
            + 0.022174192 * u**5
            + 0.0090316521 * u**6
        )
    elif year < 1600:
        u = (y - 1000) / 100
        delta_t = (
            1574.2
            - 556.01 * u
            + 71.23472 * u**2
            + 0.319781 * u**3
            - 0.8503463 * u**4
            - 0.005050998 * u**5
            + 0.0083572073 * u**6
        )
    elif year < 1700:
        t = y - 1600
        delta_t = 120 - 0.9808 * t - 0.01532 * t**2 + t**3 / 7129
    elif year < 1800:
        t = y - 1700
        delta_t = (
            8.83
            + 0.1603 * t
            - 0.0059285 * t**2
            + 0.00013336 * t**3
            - t**4 / 1174000
        )
    elif year < 1860:
        t = y - 1800
        delta_t = (
            13.72
            - 0.332447 * t
            + 0.0068612 * t**2
            + 0.0041116 * t**3
            - 0.00037436 * t**4
            + 0.0000121272 * t**5
            - 0.0000001699 * t**6
            + 0.000000000875 * t**7
        )
    elif year < 1900:
        t = y - 1860
        delta_t = (
            7.62
            + 0.5737 * t
            - 0.251754 * t**2
            + 0.01680668 * t**3
            - 0.0004473624 * t**4
            + t**5 / 233174
        )
    elif year < 1920:
        t = y - 1900
        delta_t = (
            -2.79
            + 1.494119 * t
            - 0.0598939 * t**2
            + 0.0061966 * t**3
            - 0.000197 * t**4
        )
    elif year < 1941:
        t = y - 1920
        delta_t = 21.20 + 0.84493 * t - 0.076100 * t**2 + 0.0020936 * t**3
    elif year < 1961:
        t = y - 1950
        delta_t = 29.07 + 0.407 * t - t**2 / 233 + t**3 / 2547
    elif year < 1986:
        t = y - 1975
        delta_t = 45.45 + 1.067 * t - t**2 / 260 - t**3 / 718
    elif year < 2005:
        t = y - 2000
        delta_t = (
            63.86
            + 0.3345 * t
            - 0.060374 * t**2
            + 0.0017275 * t**3
            + 0.000651814 * t**4
            + 0.00002373599 * t**5
        )
    elif year < 2050:
        t = y - 2000
        delta_t = 62.92 + 0.32217 * t + 0.005589 * t**2
    elif year < 2150:
        delta_t = -20 + 32 * ((y - 1820) / 100) ** 2 - 0.5628 * (2150 - y)
    else:
        u = (y - 1820) / 100
        delta_t = -20 + 32 * u**2

    return delta_t
