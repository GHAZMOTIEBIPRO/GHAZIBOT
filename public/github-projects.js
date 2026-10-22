"use strict";
/* Curated catalogue of exactly the fifty user-named projects, Oct 2026.
 * Status refers to GHAZI adoption, NOT upstream reliability/profitability.
 * Null paths are intentionally not clickable: no false repository mapping. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziProjects=api;
})(typeof window!=="undefined"?window:null,function(){
  const PROJECTS=[["Qullamaggie Breakout Scanner","breakout","VladPetrariu/Qullamaggie-breakout-scanner","methodology","MIT"],["Stock Screener (Minervini/CANSLIM)","breakout","xang1234/stock-screener","methodology","Apache-2.0"],["Unusual Volume Detector","breakout",null,"ambiguous","unknown"],["Anomaly Radar","breakout",null,"ambiguous","unknown"],["StockScreener","breakout",null,"ambiguous","unknown"],["finvizfinance","breakout","lit26/finvizfinance","blocked","MIT"],["unusualvolume","breakout",null,"ambiguous","unknown"],["TapeWatch","breakout",null,"ambiguous","unknown"],["Minervini Screener","breakout",null,"ambiguous","unknown"],["VCP Screener","breakout",null,"ambiguous","unknown"],["GammaGrid","options","gammagrid/gammagrid","blocked","AGPL-3.0"],["Gex-Multi","options","itsfabtrading/Gex-Multi","blocked","Apache-2.0"],["GEX Dashboard","options",null,"ambiguous","unknown"],["GEX Terminal","options",null,"ambiguous","unknown"],["0DTE Dealer Gamma","options","puneet-chandna/0DTE-dealer-gamma","blocked","PolyForm-Noncommercial"],["Options Gamma Dashboard","options",null,"ambiguous","unknown"],["MNQ GEX Dashboard","options",null,"ambiguous","unknown"],["GEX Analytics","options","pikki622/gex-analytics","reference","MIT"],["OptionLab","options",null,"ambiguous","unknown"],["Volatility Trading","options",null,"ambiguous","unknown"],["OpenTerminal","platform","ErTasselli/OpenTerminal","reference","MIT"],["FinceptTerminal","platform","Fincept-Corporation/FinceptTerminal","review","NOASSERTION"],["OpenStock","platform",null,"ambiguous","unknown"],["FinRobot","platform","AI4Finance-Foundation/FinRobot","reference","Apache-2.0"],["FinGPT","platform","AI4Finance-Foundation/FinGPT","reference","MIT"],["TradingAgents","platform","TauricResearch/TradingAgents","reference","Apache-2.0"],["QuantConnect LEAN","platform","QuantConnect/Lean","reference","Apache-2.0"],["FinRL","platform","AI4Finance-Foundation/FinRL","reference","MIT"],["FinanceToolkit","platform","JerBouma/FinanceToolkit","reference","MIT"],["Microsoft Qlib","platform","microsoft/qlib","reference","MIT"],["yfinance","source","ranaroussi/yfinance","blocked","Apache-2.0"],["yahooquery","source","dpguthrie/yahooquery","blocked","MIT"],["Alpaca Python SDK","source","alpacahq/alpaca-py","reference","Apache-2.0"],["Finnhub API SDK","source","Finnhub-Stock-API/finnhub-python","reference","Apache-2.0"],["SEC EDGAR Downloader","source","jadchaar/sec-edgar-downloader","reference","MIT"],["EdgarTools","source","dgunning/edgartools","existing","MIT"],["SEC API Python","source",null,"ambiguous","unknown"],["FinBERT","source","ProsusAI/finBERT","reference","Apache-2.0"],["Financial Sentiment Dashboard","source",null,"ambiguous","unknown"],["Pandas Datareader","source","pydata/pandas-datareader","review","NOASSERTION"],["TradingView Lightweight Charts","technical","tradingview/lightweight-charts","existing","Apache-2.0"],["TA-Lib Python","technical","TA-Lib/ta-lib-python","reference","BSD-2-Clause"],["Pandas TA Classic","technical","xgboosted/pandas-ta-classic","existing","MIT"],["Stock Indicators","technical","facioquo/stock-indicators-dotnet","reference","Apache-2.0"],["mplfinance","technical","matplotlib/mplfinance","review","NOASSERTION"],["Technical Analysis Library","technical","bukosabino/ta","reference","MIT"],["VectorBT","technical","polakowo/vectorbt","review","NOASSERTION"],["Backtrader","technical","mementum/backtrader","review","GPL-3.0"],["Backtesting.py","technical","kernc/backtesting.py","review","AGPL-3.0"],["QuantStats","technical","ranaroussi/quantstats","reference","Apache-2.0"]];
  // Verified evidence shows OUR checked-in paths, not an installation or
  // endorsement of each named upstream repository. An unnamed candidate
  // remains ambiguous even when a similar mathematical idea is implemented.
  const EVIDENCE={
    1:{kind:"own_method",path:"options_radar/vcp_minervini_shadow.py",
       note:"منهجية VCP مستقلة بالكود؛ النتائج متوقفة حتى يسمح مزود الشموع بجلبها."},
    2:{kind:"own_method",path:"options_radar/vcp_minervini_shadow.py",
       note:"اصطفاف المتوسطات قرب قمة سابقة؛ لم تُستورد فلاتر المشروع الأصلي."},
    3:{kind:"similar_idea",path:"options_radar/daily_volume_breakout_shadow.py",
       note:"تطبيق مستقل لرصد حجم التداول من الشموع المكتملة؛ اسم GitHub الأصلي لم يحدد."},
    33:{kind:"official_api_not_sdk",path:"scripts/alpaca_vcp_private.py",
       note:"واجهة Alpaca IEX الرسمية متصلة بالكود من دون حزمة SDK؛ الوصول مؤجل حتى تصريح ومفاتيح الحساب."},
    41:{kind:"existing_feature",path:"public/market-chart.js",
       note:"توجد شارتات تفاعلية في المنصة؛ لا يوجد ادعاء بوجود بيانات حية مرخصة."},
    43:{kind:"existing_feature",path:"options_radar/pandas_ta_bollinger_shadow.py",
       note:"توجد وظيفة بولنجر بحثية مرتبطة بالشموع؛ ليست مصدرًا مستقلًا."}
  };
  const EVIDENCE_KIND={
    own_method:"منهجية مطبقة بكود مستقل",
    similar_idea:"فكرة مشابهة مستقلة (الاسم الأصلي غير محدد)",
    official_api_not_sdk:"ربط API مباشر؛ لم تُستورد حزمة المشروع",
    existing_feature:"وظيفة موجودة مسبقًا"
  };
  const GROUPS={breakout:"اختراقات وفلترة",options:"أوبشن وGamma",platform:"منصات وذكاء اصطناعي",
    source:"أخبار وبيانات",technical:"شارت واختبارات"};
  const STATUS={
    methodology:"طبقنا منهجية مستقلة فقط",
    existing:"وظيفته موجودة لدينا",
    reference:"مرجع مرشح — لم ندمجه",
    blocked:"محظور الدمج المباشر أو جلب بياناته بلا إذن",
    review:"يلزم فحص الترخيص والبيانات",
    ambiguous:"اسم عام؛ المستودع المقصود غير محدد"
  };
  const validRepo=p=>typeof p==="string"&&/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(p);
  const normalized=PROJECTS.map(([name,category,repo,status,license],index)=>({
    number:index+1,name,category,repo:validRepo(repo)?repo:null,
    url:validRepo(repo)?"https://github.com/"+repo:null,status,license,
    evidence:EVIDENCE[index+1]||null}));
  function search(q="",category="all",status="all"){
    const needle=String(q).toLowerCase().trim();
    return normalized.filter(x=>(category==="all"||x.category===category)&&
      (status==="all"||x.status===status)&&
      (!needle||[x.name,x.repo||"",x.license].join(" ").toLowerCase().includes(needle)));
  }
  function render(rows){
    const node=document.getElementById("projects-results");
    if(!node)return;
    node.replaceChildren();
    for(const project of rows){
      const article=document.createElement("article");article.className="project-card";
      const top=document.createElement("div");top.className="project-top";
      const title=document.createElement("strong");title.textContent=project.number+". "+project.name;
      const cat=document.createElement("small");cat.textContent=GROUPS[project.category];
      top.append(title,cat);article.append(top);
      const body=document.createElement("p");body.textContent=STATUS[project.status];article.append(body);
      const license=document.createElement("small");
      license.textContent="ترخيص الكود: "+project.license+" · الترخيص لا يمنح حق إعادة نشر البيانات";
      article.append(license);
      if(project.evidence){
        const label=document.createElement("p");label.className="project-evidence";
        label.textContent=EVIDENCE_KIND[project.evidence.kind]+": "+
          project.evidence.note;
        article.append(label);
        const source=document.createElement("a");
        source.href="https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/blob/main/"+
          project.evidence.path;
        source.target="_blank";source.rel="noopener noreferrer";
        source.textContent="دليل الملف الموجود في مستودعنا ↗";
        article.append(source);
      }
      if(project.url){
        const anchor=document.createElement("a");
        anchor.href=project.url;anchor.target="_blank";anchor.rel="noopener noreferrer";
        anchor.textContent="فتح المستودع الأصلي على GitHub ↗";
        article.append(anchor);
      }else{
        const p=document.createElement("span");p.className="unverified";
        p.textContent="لم أثبت رابط المستودع المقصود؛ لا أضع رابطًا تخمينيًا.";article.append(p);
      }
      node.append(article);
    }
    document.getElementById("projects-count").textContent=rows.length+" / "+normalized.length;
  }
  if(typeof document!=="undefined"){
    document.addEventListener("DOMContentLoaded",()=>{
      for(const id of ["projects-query","projects-group","projects-status"])
        document.getElementById(id).addEventListener(id==="projects-query"?"input":"change",()=>{
          render(search(document.getElementById("projects-query").value,
            document.getElementById("projects-group").value,
            document.getElementById("projects-status").value));
        });
      render(search());
    });
  }
  return {PROJECTS:normalized,search,GROUPS,STATUS,validRepo,EVIDENCE_KIND};
});
