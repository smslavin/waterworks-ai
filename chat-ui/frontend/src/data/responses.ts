export const NODE_RESPONSES: Record<string, string> = {
  RawWater_01: `**Pending approval — suction starvation suspected.**\n\nRawWater_01 flow is 18% below setpoint for the last 14 minutes. Bearing temperature has risen 4°C over the same window. Pattern is consistent with suction starvation.\n\n**Proposed action:** Reduce speed by 15% and monitor for 5 minutes before re-evaluation.\n\nAwaiting operator approval before proceeding.`,

  RawWater_01_approve: `**Speed reduction applied — monitoring.**\n\nRawWater_01 speed reduced to 85%. Flow is recovering: now 6% below setpoint and improving. Bearing temperature stabilizing at 52°C. Continue monitoring for 3 minutes.`,

  RawWater_01_deny: `**Action denied — continuing observation.**\n\nOperator denied speed reduction. Maintaining current setpoint. Will escalate to critical if bearing temperature exceeds 58°C or flow drops below 40% of setpoint in the next 10 minutes.`,

  RawWater_02: `**Critical — high bearing temperature.**\n\nRawWater_02 bearing temperature at 68°C, 8°C above alarm threshold. Flow normal. No correlated upstream events.\n\n**Most likely cause:** Bearing lubrication failure or cooling line blockage.\n\n**Recommended:** Inspect bearing housing and cooling supply. Consider switching to standby if temperature continues rising.`,

  Clarifier_01: `**Normal — within all limits.**\n\nClarifier_01 operating normally. Sludge blanket depth 1.2m (setpoint 1.0–1.5m). Turbidity effluent 0.8 NTU. Rake drive current 4.1A, nominal.\n\nNo anomalies in the last 4 hours.`,

  UV_01: `**Warning — intensity degradation trend.**\n\nUV_01 lamp intensity has declined 11% over the last 7 days. Current: 87 mJ/cm². Regulatory minimum: 80 mJ/cm².\n\n**At current rate:** Will reach minimum threshold in approximately 9 days.\n\n**Recommended:** Schedule lamp replacement before next maintenance window. Dose remains compliant today.`,

  UV_02: `**Normal — recently serviced.**\n\nUV_02 lamp intensity at 98 mJ/cm² (new lamp installed 12 days ago). All sensors nominal. No intervention needed.`,

  Chlorine_01: `**Normal — residual on target.**\n\nChlorine_01 dosing at 2.3 mg/L. Effluent residual 0.71 mg/L (target 0.70–0.80 mg/L). Pump stroke 42%, flow stable.\n\nAmmonia demand stable. No breaks detected in the last 6 hours.`,

  Fluoride_01: `**Normal — within regulatory band.**\n\nFluoride_01 dosing at 0.72 mg/L effluent (target 0.70–0.75 mg/L per state regulation). Pump operating normally. No saturation or overdose indicators.`,

  HighService_01: `**Critical — discharge pressure spike.**\n\nHighService_01 discharge pressure reached 82 PSI at 14:23 (maximum setpoint: 75 PSI). Current: 79 PSI, still above limit.\n\nRawWater_02 failure may be reducing suction head to this pump.\n\n**Recommended:** Monitor closely. If pressure does not return below 75 PSI within 5 minutes, reduce speed by 10%.`,

  HighService_02: `**Normal — carrying increased load.**\n\nHighService_02 operating at 91% capacity, elevated since HighService_01 alarm. Flow output compensating. Bearing temperature 47°C, within limits. Monitor for temperature rise.`,

  FinishedWater_01: `**Normal — storage adequate.**\n\nFinishedWater_01 level at 68% (minimum operational: 40%). Inflow matches outflow. Chlorine residual 0.63 mg/L in storage.\n\nProjected time to minimum level at current draw: 9.4 hours.`,
}

export const AREA_RESPONSES: Record<string, string> = {
  Intake: `**Intake summary — 2 equipment items, 1 critical, 1 pending approval.**\n\nRawWater_01 has a pending approval for speed reduction due to suction starvation pattern. RawWater_02 is in critical alarm: bearing temperature at 68°C.\n\nTotal intake flow is 14% below target. Combined fault risk is elevated. Recommend operator attention within the next 5 minutes.`,

  Treatment: `**Treatment summary — 5 equipment items, 1 warning.**\n\nUV_01 lamp intensity at 87 mJ/cm², declining trend. Replacement recommended within 9 days.\n\nAll other treatment units (Clarifier_01, UV_02, Chlorine_01, Fluoride_01) operating normally. Water quality indicators within limits.`,

  Distribution: `**Distribution summary — 3 equipment items, 1 critical.**\n\nHighService_01 discharge pressure above setpoint (79 PSI vs 75 PSI limit). HighService_02 compensating at 91% capacity. FinishedWater_01 storage adequate at 68%.\n\nMonitor HighService_01 pressure closely. If not resolved within 5 minutes, speed reduction recommended.`,
}

export const CRUMB_RESPONSES: Record<string, string> = {
  plant: `**Waterworks Plant — 3 process areas, 2 critical alarms.**\n\nIntake: 1 critical (RawWater_02 bearing), 1 pending approval (RawWater_01 suction starvation).\nTreatment: 1 warning (UV_01 lamp degradation).\nDistribution: 1 critical (HighService_01 pressure).\n\nOverall plant status: **Degraded.** Operator action required in Intake and Distribution.`,

  region: `**Region — 4 active plants.**\n\nWaterworks: Degraded (2 critical)\nEastside: Normal\nNorthgate: Warning (1 — scheduled maintenance)\nRiverfront: Normal\n\nNo region-wide incidents. Waterworks requires attention.`,

  enterprise: `**Enterprise — 12 sites, 3 with active alarms.**\n\nWaterworks: Degraded\nMaplewood: Warning\nHillside: Critical (1)\n\nAll other sites normal. Escalation required at Hillside.`,
}
