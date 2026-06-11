#!/usr/bin/env bash
# Run the Ant Design Vue reference extractor on sample_form.vue.
# Expected: 4 fields (employee_name / department / email / start_date).
set -euo pipefail
cd "$(dirname "$0")"
python3 extract_fields_antd.py sample_form.vue
