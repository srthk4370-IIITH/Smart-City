# rsn p2 row audit

85 rows (60 new p2, 40 replay): bad 3 = 3.5% (limit 5%)

- inc3-037094 [agent_miss+tool:related_context]: id S2.E4 not in prompt; id S2.E1 not in prompt
- inc3-041681 [replaced_shift+tool:get_action_history]: id S2.E3 not in prompt
- inc3-027210 [acidic+tool:related_context]: id S2.E4 not in prompt

RESULT: PASS
