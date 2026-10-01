#pragma once
namespace bootstrap {
struct Node { int left; int right; int feature; float threshold; float votes[8]; };
constexpr int kFeatureCount=6; constexpr float kAgentImpute[]={ 0f, 0f, 0f, 0f, 0f, 0f }; constexpr float kOrchestratorImpute[]={ 0f, 0f, 0f, 0f, 0f, 0f, 0f };
constexpr const char* kAgentClasses[]={ "air_nominal", "co2_elevated", "pm25_elevated" }; constexpr const char* kPlanClasses[]={ "air_then_occupancy_energy_weather", "air_then_weather", "no_call" };
constexpr int kAgentNodeCount=9; constexpr int kOrchestratorNodeCount=9;
constexpr Node kAgentNodes[]={
  {1, 6, 0, 999.5f, {0.333333333f, 0.333333333f, 0.333333333f}},
  {2, 5, 3, 197f, {0.5f, 0f, 0.5f}},
  {3, 4, 2, 29.2399998f, {1f, 0f, 0f}},
  {-1, -1, -2, -2f, {1f, 0f, 0f}},
  {-1, -1, -2, -2f, {1f, 0f, 0f}},
  {-1, -1, -2, -2f, {0f, 0f, 1f}},
  {7, 8, 1, 28.6449995f, {0f, 1f, 0f}},
  {-1, -1, -2, -2f, {0f, 1f, 0f}},
  {-1, -1, -2, -2f, {0f, 1f, 0f}}
};
constexpr Node kOrchestratorNodes[]={
  {1, 6, 0, 999.5f, {0.333333333f, 0.333333333f, 0.333333333f}},
  {2, 5, 5, 24.5f, {0f, 0.5f, 0.5f}},
  {3, 4, 1, 21.3550005f, {0f, 0f, 1f}},
  {-1, -1, -2, -2f, {0f, 0f, 1f}},
  {-1, -1, -2, -2f, {0f, 0f, 1f}},
  {-1, -1, -2, -2f, {0f, 1f, 0f}},
  {7, 8, 0, 1005.5f, {1f, 0f, 0f}},
  {-1, -1, -2, -2f, {1f, 0f, 0f}},
  {-1, -1, -2, -2f, {1f, 0f, 0f}}
};
}
