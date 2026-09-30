#include <cstdlib>
#include <iostream>
#include <cmath>
#include <string>
#include "edge_policy.h"

using namespace bootstrap;
int predict(const Node* nodes, int node_count, const float* values) {
  int node = 0;
  while (node >= 0 && node < node_count && nodes[node].left != -1) {
    const Node& n = nodes[node]; node = values[n.feature] <= n.threshold ? n.left : n.right;
  }
  int best = 0; for (int i = 1; i < 8; ++i) if (nodes[node].votes[i] > nodes[node].votes[best]) best = i;
  return best;
}
const char* agents(const char* plan) {
  std::string p(plan);
  if (p == "air_then_occupancy_energy_weather") return "air_quality,occupancy,energy,weather";
  if (p == "air_then_weather_occupancy_energy") return "air_quality,weather,occupancy,energy";
  if (p == "air_then_weather") return "air_quality,weather";
  if (p == "air_only") return "air_quality";
  return "";
}
int main(int argc, char** argv) {
  if (argc != kFeatureCount + 1) { std::cerr << "usage: bootstrap_policy_runner CO2 TEMP RH PM25 PM10 AQI\n"; return 2; }
  float features[kFeatureCount]; for (int i=0;i<kFeatureCount;++i) features[i] = std::strtof(argv[i+1], nullptr);
  int agent_idx = predict(kAgentNodes, kAgentNodeCount, features);
  float orchestration[kFeatureCount+1]; for(int i=0;i<kFeatureCount;++i) orchestration[i]=features[i]; orchestration[kFeatureCount]=static_cast<float>(agent_idx);
  int plan_idx = predict(kOrchestratorNodes, kOrchestratorNodeCount, orchestration);
  std::cout << "{\"agent\":\"air_quality\",\"agent_triage\":\"" << kAgentClasses[agent_idx] << "\",\"orchestration_plan\":\"" << kPlanClasses[plan_idx] << "\",\"agents_in_order\":\"" << agents(kPlanClasses[plan_idx]) << "\",\"root_cause\":null,\"requires_human_approval\":true}" << std::endl;
}
