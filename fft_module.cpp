#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <fftw3.h>
#include <vector>
#include <cmath>

namespace py = pybind11;

py::array_t<std::complex<double>> rfft(py::array_t<double> input) {
    // 获取输入数组信息
    auto buf = input.request();
    double *ptr = static_cast<double*>(buf.ptr);
    size_t n = buf.size;
    
    // 输出长度：n//2 + 1
    size_t n_out = n / 2 + 1;
    
    // 分配 FFTW 输入输出数组
    fftw_complex *in, *out;
    in = (fftw_complex*) fftw_malloc(sizeof(fftw_complex) * n);
    out = (fftw_complex*) fftw_malloc(sizeof(fftw_complex) * n_out);
    
    // 实部填入输入，虚部为 0
    for (size_t i = 0; i < n; ++i) {
        in[i][0] = ptr[i];
        in[i][1] = 0.0;
    }
    
    // 创建计划（实数到复数 FFT，一次性）
    fftw_plan plan = fftw_plan_dft_r2c_1d(n, ptr, out, FFTW_ESTIMATE);
    fftw_execute(plan);
    
    // 复制结果到 Python 数组
    py::array_t<std::complex<double>> result({n_out});
    auto result_buf = result.request();
    std::complex<double>* result_ptr = static_cast<std::complex<double>*>(result_buf.ptr);
    for (size_t i = 0; i < n_out; ++i) {
        result_ptr[i] = std::complex<double>(out[i][0], out[i][1]);
    }
    
    // 清理
    fftw_destroy_plan(plan);
    fftw_free(in);
    fftw_free(out);
    
    return result;
}

PYBIND11_MODULE(fft_cpp, m) {
    m.doc() = "Fast FFT using FFTW";
    m.def("rfft", &rfft, "Real FFT (return complex array)");
}