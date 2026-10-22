"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {PROJECTS,search,validRepo}=require("../public/github-projects.js");
assert.equal(PROJECTS.length,50);
assert.equal(PROJECTS.filter(p=>p.url!==null).length,37);
assert.equal(PROJECTS.filter(p=>p.status==="ambiguous"&&p.url===null).length,13);
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

assert.equal(search("","all","evidence").length,7);
assert.equal(search("","source","evidence").length,1);
for(const p of search("","all","evidence")){
  assert.ok(["own_method","similar_idea","official_api_not_sdk","existing_feature"]
    .includes(p.evidence.kind));
  assert.ok(fs.existsSync(path.join(__dirname,"..",p.evidence.path)));
  assert.ok(p.evidence.note.length>25);
}
assert.equal(PROJECTS.find(p=>p.number===3).status,"reference");
assert.equal(PROJECTS.find(p=>p.number===3).repo,"SamPom100/UnusualVolumeDetector");
assert.equal(PROJECTS.find(p=>p.number===33).evidence.kind,"official_api_not_sdk");
assert.equal(PROJECTS.find(p=>p.number===1).evidence.kind,"own_method");
assert.equal(PROJECTS.filter(p=>p.evidence?.kind==="own_method").length,2);

const page=fs.readFileSync(path.join(__dirname,"../public/github-projects.html"),"utf8");
const main=fs.readFileSync(path.join(__dirname,"../public/index.html"),"utf8");
assert.ok(page.includes('src="./github-projects.js'));
assert.ok(page.includes('id="projects-results"'));
assert.ok(page.includes('value="evidence"'));
assert.ok(main.includes('href="./github-projects.html"'));
console.log("50 GitHub names, 37 verified repository paths, 13 unlinked ambiguous titles");

assert.equal(PROJECTS.find(p=>p.number===19).license,"GPL-3.0");
assert.equal(PROJECTS.find(p=>p.number===50).status,"existing");
