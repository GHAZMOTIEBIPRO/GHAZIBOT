'use strict';
const assert=require('node:assert/strict');
const {weeklySetupLine}=require('../public/terminal-hub.js');
const input={available:true,research_only:true,source_family:'yahoo',
  option_execution_eligible:false,independent_confirmation:false,
  source_last_daily_bar:'2026-10-21',stage:'TIGHT_WATCH',weekly_context:{
    schema:'ghazi.weekly_setup_shadow.v1',available:true,research_only:true,
    independent_confirmation:false,option_execution_eligible:false,weeks_used:12,
    range_ratio:.65,trend_up:true,range_contraction:true,weekly_breakout:false,
    last_complete_week:'2026-10-16',status:'DAILY_WEEKLY_ALIGNED'}};
assert.match(weeklySetupLine(input),/توافق الانكماش/);
assert.equal(weeklySetupLine(input,true),null);
assert.equal(weeklySetupLine({...input,source_family:'alpaca_iex'}),null);
for(const changes of [{last_complete_week:'2026-10-23'}, {last_complete_week:'2026-10-15'},
  {last_complete_week:'invalid'}, {option_execution_eligible:true}, {trend_up:false},
  {weeks_used:1}, {range_ratio:NaN}, {status:'BUY'}]){
  assert.equal(weeklySetupLine({...input,weekly_context:{...input.weekly_context,...changes}}),null);
}
assert.match(weeklySetupLine({...input,weekly_context:{...input.weekly_context,
  status:'NO_WEEKLY_CONFIRMATION',trend_up:false}}),/لا تأكيد/);
console.log('Weekly UI rejects partial, inconsistent, non-public and execution-authoritative context: PASS');
