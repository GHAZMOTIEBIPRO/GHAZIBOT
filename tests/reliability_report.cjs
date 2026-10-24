const assert=require('node:assert/strict');
const {describe}=require('../public/reliability-report.js');
const now=Date.parse('2026-10-24T12:00:00Z');
const report={schema:'ghazi.reliability.v1',generated_at:'2026-10-24T10:00:00Z',decision_authority:false,
raw_market_data_published:false,statistics_input_verified:true,quality:{status:'VALID',records:5,failure_count:0},
integrity:{tracked:5,ever_changed:0},statistics_status:'INSUFFICIENT_EVIDENCE'};
assert.match(describe(report,now).join(' '),/العينة غير كافية/);
for(const value of [null,{...report,decision_authority:true},{...report,generated_at:'2030-01-01T00:00:00Z'},
{...report,generated_at:'2026-10-01T00:00:00Z'},{...report,generated_at:'2026-10-24T10:00:00'}])
assert.match(describe(value,now)[0],/غير متاح/);
console.log('Reliability UI guards passed');

assert.match(describe({...report,statistics_input_verified:false},now).join(" "),/محجوب/);
