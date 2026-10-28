// Cost of building one streaming progress line (14 streams, ~2 tokens each per step), and of the
// label-constraint check on an allowed token: g++ -O2 -std=c++17 bench_stream.cpp && ./a.out
#include "htpd_logic.h"

#include <chrono>
#include <iostream>

int main() {
    using clk = std::chrono::steady_clock;
    htpd::StepStream ss;
    ss.reset(14);
    std::string l;
    const int N = 200000;
    size_t bytes = 0;
    auto t0 = clk::now();
    for (int k = 0; k < N; ++k) {
        for (int s = 0; s < 14; ++s) { ss.add(s, " 28.9"); ss.add(s, " \xC2\xB0" "C"); }
        ss.line(l);
        bytes += l.size();
    }
    double us = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / N;
    std::cout << "stream line, 14 streams: " << us << " us/step, " << bytes / N << " bytes\n";

    htpd::Labels L = {{"pattern", {"stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase",
                                    "step_decrease", "exponential_increase", "oscillation", "throttling", "flatline", "erratic"}},
                      {"status", {"normal", "warning", "critical", "sensor_fault"}}};
    htpd::JState st;
    for (char c : std::string("{\"pattern\": \"stable\", \"status\": \"normal\", \"observations\": [\"x")) st.step(c);
    int ok = 0;
    t0 = clk::now();
    for (int k = 0; k < N; ++k) ok += htpd::piece_allowed(st, " 28.9 kW", L);
    us = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / N;
    std::cout << "piece_allowed (outside a constrained value): " << us * 1000 << " ns/token (" << ok << ")\n";
    htpd::JState sp;
    for (char c : std::string("{\"pattern\": \"")) sp.step(c);
    t0 = clk::now();
    for (int k = 0; k < N; ++k) ok += htpd::piece_allowed(sp, "gradual", L);
    us = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / N;
    std::cout << "piece_allowed (inside pattern): " << us * 1000 << " ns/token\n";
}
