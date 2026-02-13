
import re

log_file = "/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/full_log_v36.txt"
with open(log_file, 'r') as f:
    content = f.read()

scenarios = re.split(r'──────────────────────────────────────────────────────────────────────\n场景 ', content)
failed_scenarios = []

for s in scenarios[1:]:
    lines = s.split('\n')
    header = lines[0]
    scenario_num = header.split('/')[0]
    
    if "稳态(真实参数): ❌ 否" in s:
        loop_type_match = re.search(r'回路类型: (\w+)', s)
        loop_type = loop_type_match.group(1) if loop_type_match else "unknown"
        failed_scenarios.append(f"{scenario_num} ({loop_type})")

print(f"Failed Scenarios ({len(failed_scenarios)}): {', '.join(failed_scenarios)}")
