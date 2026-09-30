/* Smart City Edge AI - Client JS Logic */

let currentPresets = {};

// Load presets on initialization and start NPU warmup status polling
document.addEventListener("DOMContentLoaded", async () => {
    try {
        const res = await fetch("/api/presets");
        if (res.ok) {
            currentPresets = await res.json();
        }
    } catch (e) {
        console.warn("Presets fetch deferred:", e);
    }
    // Poll NPU warmup status every 3 seconds until warm
    pollWarmupStatus();
});

async function pollWarmupStatus() {
    try {
        const res = await fetch("/api/warmup_status");
        if (res.ok) {
            const data = await res.json();
            const badge = document.getElementById("warmupBadge");
            const val   = document.getElementById("warmupVal");
            if (data.warm) {
                badge.style.background      = "rgba(16,185,129,0.15)";
                badge.style.borderColor     = "rgba(16,185,129,0.5)";
                badge.style.color           = "#6ee7b7";
                badge.childNodes[0].textContent = "⚡ ";
                val.textContent = "NPU Active — 1-Call Mode";
                return; // Stop polling — stay green
            } else {
                val.textContent = data.device_connected ? "NPU connecting…" : "No QIDK device";
            }
        }
    } catch (e) { /* server not up yet, retry */ }
    setTimeout(pollWarmupStatus, 3000);
}


function updateVal(id, unit) {
    const el = document.getElementById(id);
    const display = document.getElementById("val_" + id);
    if (el && display) {
        let val = parseFloat(el.value);
        display.innerText = `${val.toFixed(1)} ${unit}`.trim();
    }
}

function loadPreset(key) {
    const preset = currentPresets[key];
    if (!preset || !preset.data) return;
    
    for (const [field, value] of Object.entries(preset.data)) {
        const input = document.getElementById(field);
        if (input) {
            input.value = value;
            // Infer unit for label update
            let unit = "";
            if (field.includes("ppm")) unit = "ppm";
            else if (field.includes("ug_m3")) unit = "µg/m³";
            else if (field.includes("temperature")) unit = "°C";
            else if (field.includes("humidity")) unit = "%";
            else if (field.includes("kw")) unit = "kW";
            else if (field.includes("lpm")) unit = "L/min";
            else if (field.includes("db")) unit = "dB";
            else if (field.includes("voltage")) unit = "V";
            
            updateVal(field, unit);
        }
    }
    
    // Automatically trigger pipeline execution on preset click
    document.getElementById("btnSubmit").click();
}

async function handleFormSubmit(event) {
    event.preventDefault();
    
    const btn = document.getElementById("btnSubmit");
    const originalBtnText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="pulse-dot"></span> Processing Edge AI Pipeline...`;
    
    // Gather sensor values
    const fields = ["co2_ppm", "pm25_ug_m3", "pm10_ug_m3", "temperature_c", "relative_humidity_pct", "energy_kw", "water_flow_lpm", "occupancy_count", "noise_db", "grid_voltage_v"];
    const payload = {};
    fields.forEach(f => {
        const el = document.getElementById(f);
        payload[f] = el ? parseFloat(el.value) : 0.0;
    });
    
    try {
        const t0 = performance.now();
        const res = await fetch("/api/evaluate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        const clientLatency = Math.round(performance.now() - t0);
        
        document.getElementById("latencyVal").innerText = `${data.total_latency_ms || clientLatency} ms`;
        
        renderResults(data);
    } catch (err) {
        console.error("Evaluation Error:", err);
        alert("Failed to communicate with Edge AI web server. Make sure server is running.");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnText;
    }
}

function renderResults(data) {
    const isAnomaly = data.anomaly_detected;
    
    // 1. Status Card Update
    const statusCard = document.getElementById("statusCard");
    const statusBadgeIcon = document.getElementById("statusBadgeIcon");
    const statusTitle = document.getElementById("statusTitle");
    const statusSubtitle = document.getElementById("statusSubtitle");
    const scoreVal = document.getElementById("scoreVal");
    const scoreProgress = document.getElementById("scoreProgress");
    
    const scorePct = Math.round((data.anomaly_score || 0) * 100);
    scoreVal.innerText = `${scorePct}%`;
    scoreProgress.style.width = `${scorePct}%`;
    
    if (isAnomaly) {
        statusCard.style.borderColor = "rgba(244, 63, 94, 0.5)";
        statusCard.style.boxShadow = "0 0 20px rgba(244, 63, 94, 0.2)";
        statusBadgeIcon.innerText = "🔴";
        statusTitle.innerText = "ANOMALY DETECTED";
        statusTitle.style.color = "var(--accent-rose)";
        statusSubtitle.innerText = `Threshold breach detected. Triggered Orchestrator & Multi-Domain Agents.`;
    } else {
        statusCard.style.borderColor = "rgba(16, 185, 129, 0.3)";
        statusCard.style.boxShadow = "none";
        statusBadgeIcon.innerText = "🟢";
        statusTitle.innerText = "SYSTEM NOMINAL";
        statusTitle.style.color = "var(--accent-emerald)";
        statusSubtitle.innerText = "All telemetry channels are within normal operational limits.";
    }
    
    // 2. Orchestrator Multi-Domain Plan Flow
    const agentsFlow = document.getElementById("agentsFlow");
    const orchPlanTag = document.getElementById("orchPlanTag");
    
    if (data.orchestrator_plan && data.orchestrator_plan.agents_in_order) {
        const agents = data.orchestrator_plan.agents_in_order;
        orchPlanTag.innerText = `Plan: ${data.orchestrator_plan.orchestration_plan}`;
        
        let flowHTML = "";
        agents.forEach((ag, idx) => {
            const domainName = ag.replace("_", " ").toUpperCase();
            flowHTML += `<div class="agent-node"><span>🤖</span> ${domainName}</div>`;
            if (idx < agents.length - 1) {
                flowHTML += `<span class="flow-arrow">➔</span>`;
            }
        });
        flowHTML += `<span class="flow-arrow">➔</span><div class="agent-node" style="border-color: var(--accent-emerald); color: var(--accent-emerald);"><span>🧠</span> QWEN REASONER</div>`;
        agentsFlow.innerHTML = flowHTML;
    } else {
        orchPlanTag.innerText = "Standby";
        agentsFlow.innerHTML = `<div class="flow-placeholder">No active domain agents called (Baseline State).</div>`;
    }
    
    // 3. Domain Agent Outputs
    const agentCardsContainer = document.getElementById("agentCardsContainer");
    if (data.agent_outputs && data.agent_outputs.length > 0) {
        let agentHTML = "";
        data.agent_outputs.forEach(ag => {
            agentHTML += `
                <div class="agent-output-box">
                    <div class="agent-box-title">
                        <span>🤖 Agent: ${ag.domain.toUpperCase()}</span>
                        <span class="tag tag-cyan">Confidence: ${Math.round((ag.confidence || 0.9) * 100)}%</span>
                    </div>
                    <div class="agent-hypothesis">${ag.hypothesis || ag.triage}</div>
                    <div class="agent-evidence">Cited Telemetry: [${(ag.evidence_cited || []).join(", ")}]</div>
                </div>
            `;
        });
        agentCardsContainer.innerHTML = agentHTML;
    } else {
        agentCardsContainer.innerHTML = `<div class="placeholder-text">Telemetry within baseline bounds. No domain agent execution required.</div>`;
    }
    
    // 4. Qwen Cross-Domain Synthesis (Root Cause Report)
    const synthesisContent = document.getElementById("synthesisContent");
    if (data.root_cause_report) {
        const rcr = data.root_cause_report;
        let factorsHTML = (rcr.evidence || []).map(f => `<li>Evidence Cited: ${f}</li>`).join("");
        let actionsArr = rcr.recommendation ? rcr.recommendation.split('\\n') : [];
        let actionsHTML = actionsArr.map(a => `<p>${a}</p>`).join("");
        
        synthesisContent.innerHTML = `
            <div class="synthesis-hypothesis">${rcr.root_cause}</div>
            <ul class="factors-list">
                ${factorsHTML}
            </ul>
            <div class="actions-box">
                <h4>🛡️ Recommended Mitigation Actions (Requires Human Approval: ${rcr.requires_human_approval})</h4>
                ${actionsHTML}
            </div>
        `;
    } else {
        synthesisContent.innerHTML = `<div class="placeholder-text">Cross-domain synthesis inactive. Operating in baseline monitoring mode.</div>`;
    }
    
    // 5. Execution Trace Timeline
    const traceTimeline = document.getElementById("traceTimeline");
    if (data.trace_logs && data.trace_logs.length > 0) {
        let traceHTML = "";
        data.trace_logs.forEach(t => {
            traceHTML += `
                <div class="trace-item">
                    <span class="trace-name">${t.step}: ${t.detail}</span>
                    <span class="trace-time">${t.time_ms} ms</span>
                </div>
            `;
        });
        traceTimeline.innerHTML = traceHTML;
    } else {
        traceTimeline.innerHTML = `<div class="placeholder-text">No execution trace recorded.</div>`;
    }
}
