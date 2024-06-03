#include <omp.h>
#include <functional.hpp>
#include <functional>
namespace libthermo {

template <floating T>
constexpr bool monotonic(const T x[], const size_t size, direction direction) noexcept {
    if (direction == direction::increasing) {
        for (size_t i = 1; i < size; i++)
            if (x[i] < x[i - 1])
                return false;
    } else {
        for (size_t i = 1; i < size; i++)
            if (x[i] > x[i - 1])
                return false;
    }

    return true;
}

template <floating T>
constexpr T degrees(const T radians) noexcept {
    return radians * 180.0 / M_PI;
}

template <floating T>
constexpr T radians(const T degrees) noexcept {
    return degrees * M_PI / 180.0;
}

template <floating T>
constexpr T norm(const T x, const T x0, const T x1) noexcept {
    return (x - x0) / (x1 - x0);
}

template <floating T>
constexpr T linear_interpolate(
  const T x, const T x0, const T x1, const T y0, const T y1
) noexcept {
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0);
}

template <floating T, typename C>
constexpr size_t lower_bound(const T array[], const int N, const T& value, const C cmp) {
    int len = N;
    size_t idx = 0;
    while (len > 1) {
        int half = len / 2;
        idx += cmp(array[idx + half - 1], value) * half;
        len -= half;
    }
    return idx;
}

template <floating T, typename C>
constexpr size_t upper_bound(const T array[], const int N, const T& value, const C cmp) {
    int len = N;
    size_t idx = 0;
    while (len > 1) {
        int half = len / 2;
        idx += !cmp(value, array[idx + half - 1]) * half;
        len -= half;
    }
    return idx;
}

template <floating T>
size_t search_sorted(const T x[], const T value, const size_t size, const bool inverted) noexcept {
    if (inverted)
        return lower_bound(x, size, value, std::greater_equal());

    return upper_bound(x, size, value, std::less_equal());
}

template <floating T>
constexpr T interpolate_z(const size_t size, const T x, const T xp[], const T fp[]) noexcept {
    const size_t i = lower_bound(xp, size, x, std::greater_equal());
    if (i == 0)
        return fp[0];

    return linear_interpolate(x, xp[i - 1], xp[i], fp[i - 1], fp[i]);
}

template <floating T>
constexpr T heaviside(const T x, const T h0) noexcept {
    if (isnan(x))
        return NAN;
    else if (x == 0)
        return h0;
    else if (x < 0)
        return 0.0;

    return 1.0;
}

template <floating T>
constexpr T rk2(Fn<T, T, T> fn, T x0, T x1, T y, T step /* = .1 */) noexcept {
    T k1, delta, abs_delta;
    size_t N = 1;

    delta = x1 - x0;
    abs_delta = fabs(delta);
    if (abs_delta > step) {
        N = (size_t)ceil(abs_delta / step);
        delta = delta / (T)N;
    }

    for (size_t i = 0; i < N; i++) {
        k1 = delta * fn(x0, y);
        y += delta * fn(x0 + delta * 0.5, y + k1 * 0.5);
        x0 += delta;
    }

    return y;
}

template <floating T, floating... Args>
constexpr T fixed_point(
  const Fn<T, T, T, Args...> fn,
  const size_t max_iters,
  const T eps,
  const T x0,
  const Args... args
) noexcept {
    T p0, p1, p2, delta, err;

    p0 = x0;
    for (size_t i = 0; i < max_iters; i++) {
        p1 = fn(p0, x0, args...);
        p2 = fn(p1, x0, args...);
        delta = p2 - 2.0 * p1 + p0;
        if (delta)
            p2 = p0 - pow(p1 - p0, 2) / delta; /* delta squared */

        err = p2;
        if (p0)
            err = fabs((p2 - p0) / p0); /* absolute relative error */

        if (err < eps)
            return p2;

        p0 = p2;
    }

    return NAN;
}

}  // namespace libthermo