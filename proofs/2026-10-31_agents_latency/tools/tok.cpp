// tok: tokenize records (separated by \x1e) from stdin with a vocab-only GGUF; one line of ids per record.
#include "llama.h"
#include <cstdio>
#include <string>
#include <vector>
#include <iostream>
#include <sstream>
int main(int argc, char ** argv) {
    llama_backend_init();
    auto mp = llama_model_default_params(); mp.vocab_only = true;
    llama_model * m = llama_model_load_from_file(argv[1], mp);
    const llama_vocab * v = llama_model_get_vocab(m);
    std::stringstream ss; ss << std::cin.rdbuf(); std::string all = ss.str();
    size_t a = 0;
    while (a <= all.size()) {
        size_t b = all.find('\x1e', a); if (b == std::string::npos) b = all.size();
        std::string s = all.substr(a, b - a);
        if (b == all.size() && s.empty()) break;
        std::vector<llama_token> t(s.size() + 16);
        int n = llama_tokenize(v, s.data(), s.size(), t.data(), t.size(), false, true);
        if (n < 0) { t.resize(-n); n = llama_tokenize(v, s.data(), s.size(), t.data(), t.size(), false, true); }
        for (int i = 0; i < n; ++i) printf(i ? " %d" : "%d", t[i]);
        printf("\n");
        a = b + 1;
    }
    return 0;
}
