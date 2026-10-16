// Link stub: the scheduler only logs through Env when an Env is set; the host
// test passes none, so this is never called.
#include "Logger.hpp"
void genie::log::Logger::log(const GenieLog_Level_t, const char*, const long, const char*, ...) {}
