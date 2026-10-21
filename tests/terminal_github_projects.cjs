"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {PROJECTS,search,validRepo}=require("../public/github-projects.js");
assert.equal(PROJECTS.length,50);
assert.equal(PROJECTS.filter(p=>p.url!==null).length,34);
assert.equal(PROJECTS.filter(p=>p.status==="ambiguous"&&p.url===null).length,16);
assert.equal(new Set(PROJECTS.map(p=>p.number)).size,50);
assert.deepEqual(search("GammaGrid").map(x=>x.name),["GammaGrid"]);
assert.equal(search("delta","options").length,0);
assert.equal(search("","source").length,10);
assert.equal(search("","technical").length,10);
assert.equal(search("","breakout","methodology").length,2);
assert.equal(PROJECTS.find(p=>p.name==="GammaGrid").license,"AGPL-3.0");
assert.equal(PROJECTS.find(p=>p.name==="GammaGrid").status,"blocked");
assert.equal(PROJECTS.find(p=>p.name==="0DTE Dealer Gamma").status,"blocked");
assert.equal(PROJECTS.find(p=>p.name==="Stock Indicators").repo,
  "facioquo/stock-indicators-dotnet");
assert.equal(PROJECTS.find(p=>p.name==="EdgarTools").status,"existing");
assert.equal(PROJECTS.find(p=>p.name==="Qullamaggie Breakout Scanner").status,"methodology");
assert.equal(PROJECTS.find(p=>p.name==="Stock Screener (Minervini/CANSLIM)").status,"methodology");
assert.equal(validRepo("fake.invalid / abc"),false);
for(const p of PROJECTS){
  if(p.repo)assert.equal(p.url,"https://github.com/"+p.repo);
  else assert.equal(p.url,null);
}
const page=fs.readFileSync(path.join(__dirname,"../public/github-projects.html"),"utf8");
const main=fs.readFileSync(path.join(__dirname,"../public/index.html"),"utf8");
assert.ok(page.includes('src="./github-projects.js'));
assert.ok(page.includes('id="projects-results"'));
assert.ok(main.includes('href="./github-projects.html"'));
console.log("50 GitHub names, 34 verified repository paths, 16 unlinked ambiguous titles");
