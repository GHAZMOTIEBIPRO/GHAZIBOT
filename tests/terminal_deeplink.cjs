"use strict";
const assert=require("node:assert/strict");
const {symbolFromLink}=require("../public/terminal-hub.js");

assert.equal(symbolFromLink("?chart=mu"),"MU");
assert.equal(symbolFromLink("?chart=BRK.B"),"BRK.B");
assert.equal(symbolFromLink("?x=1"),null);
assert.equal(symbolFromLink(""),null);
assert.equal(symbolFromLink("?chart=%3Cscript%3E"),null);
assert.equal(symbolFromLink("?chart=TOOLONGSYMBOL1"),null);
assert.equal(symbolFromLink("?chart=1ABC"),null);
console.log("terminal deep link ok");
