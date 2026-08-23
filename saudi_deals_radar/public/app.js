const wm=document.querySelector(".watermark");
if(wm) wm.innerHTML=Array.from({length:36},()=>"<span>رأس الزعراء</span>").join("");

const $ = (s)=>document.querySelector(s);
let all=[], mode="saudi", store="الكل", category="الكل", nationalOnly=false;

const money=(n,c="SAR")=>{try{return new Intl.NumberFormat("ar-SA",{style:"currency",currency:c||"SAR",maximumFractionDigits:2}).format(n)}catch{return `${n} ${c||"SAR"}`}};
const ago=(iso)=>{const m=Math.max(0,Math.round((Date.now()-new Date(iso).getTime())/60000));if(m<60)return `منذ ${m} د`;if(m<1440)return `منذ ${Math.round(m/60)} س`;return `منذ ${Math.round(m/1440)} يوم`};
const esc=(s="")=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const channel=x=>x.marketChannel||"saudi";

function modeRows(){
  if(mode==="saudi") return all.filter(x=>channel(x)==="saudi");
  if(mode==="global") return all.filter(x=>channel(x)==="global");
  const rows=[...all].sort((a,b)=>(b.score||0)-(a.score||0));
  const storeN=new Map(), catN=new Map(), out=[];
  for(const x of rows){
    const s=storeN.get(x.store)||0, c=catN.get(x.category||"منوع")||0;
    if(s>=4 || c>=10) continue;
    out.push(x); storeN.set(x.store,s+1); catN.set(x.category||"منوع",c+1);
  }
  return out;
}

function filteredRows(){
  const q=$("#search").value.trim().toLowerCase();
  const min=Number($("#minDiscount").value);
  let rows=modeRows().filter(x=>(store==="الكل"||x.store===store) && (category==="الكل"||(x.category||"منوع")===category) && (x.discountPercent||0)>=min && (!nationalOnly||x.seasonalCampaign==="saudi-national-day-96") && (!q||`${x.title} ${x.store} ${x.category||""}`.toLowerCase().includes(q)));
  const sort=$("#sort").value;
  if(sort==="score")rows.sort((a,b)=>(b.score||0)-(a.score||0));
  if(sort==="discount")rows.sort((a,b)=>(b.discountPercent||0)-(a.discountPercent||0));
  if(sort==="priceAsc")rows.sort((a,b)=>(a.currentPrice||0)-(b.currentPrice||0));
  if(sort==="fresh")rows.sort((a,b)=>new Date(b.verifiedAt)-new Date(a.verifiedAt));
  return rows;
}

function render(){
  const rows=filteredRows();
  $("#empty").hidden=rows.length>0;
  $("#grid").innerHTML=rows.map(x=>`
    <article class="card">
      <div class="img">${x.imageUrl?`<img loading="lazy" src="${esc(x.imageUrl)}" alt="">`:"<span>لا توجد صورة</span>"}</div>
      <div class="body">
        <div class="topline"><span class="store">${esc(x.store)}</span>${x.seasonal?`<span class="season-tag">🇸🇦 ${esc(x.seasonalLabel||"عرض موسمي")}</span>`:""}</div>
        <div class="title">${esc(x.title)}</div>
        <div class="category">${esc(x.category||"منوع")}</div>
        <div class="price"><span class="now">${money(x.currentPrice,x.currency)}</span>${x.previousPrice?`<span class="old">${money(x.previousPrice,x.currency)}</span>`:""}<span class="discount">−${x.discountPercent}%</span></div>
        <div class="meta">
          <span class="badge">توفير ${money(x.savings,x.currency)}</span>
          ${x.lowest30d?`<span class="badge">أقل سعر 30 يوم</span>`:""}
          <span class="badge">✓ متوفر</span>
          <span class="badge">${x.shipping==="confirmed"?"✓ شحن للسعودية":"✓ متجر/واجهة سعودية"}</span>
          <span class="badge">${ago(x.verifiedAt)}</span>
        </div>
        <a class="buy" href="${esc(x.productUrl)}" target="_blank" rel="noopener noreferrer">فتح العرض</a>
      </div>
    </article>`).join("");
}

function chips(){
  const base=modeRows();
  const cats=["الكل",...[...new Set(base.map(x=>x.category||"منوع"))].sort((a,b)=>a.localeCompare(b,"ar"))];
  $("#categoryChips").innerHTML=cats.map(s=>`<button class="chip ${s===category?"active":""}" data-category="${esc(s)}">${esc(s)}</button>`).join("");
  const stores=["الكل",...[...new Set(base.filter(x=>category==="الكل"||(x.category||"منوع")===category).map(x=>x.store))].sort((a,b)=>a.localeCompare(b,"ar"))];
  $("#storeChips").innerHTML=stores.map(s=>`<button class="chip ${s===store?"active":""}" data-store="${esc(s)}">${esc(s)}</button>`).join("");
}

$("#categoryChips").onclick=e=>{const b=e.target.closest("[data-category]");if(!b)return;category=b.dataset.category;store="الكل";nationalOnly=false;chips();render()};
$("#storeChips").onclick=e=>{const b=e.target.closest("[data-store]");if(!b)return;store=b.dataset.store;render();chips()};
for(const id of ["search","minDiscount","sort"])$("#"+id).addEventListener("input",render);

document.querySelector(".mode-tabs").onclick=e=>{
  const b=e.target.closest("[data-mode]"); if(!b)return;
  mode=b.dataset.mode; store="الكل"; category="الكل"; nationalOnly=false;
  document.querySelectorAll(".mode").forEach(x=>x.classList.toggle("active",x.dataset.mode===mode));
  chips(); render();
};

$("#showNationalDay").onclick=()=>{mode="saudi";store="الكل";category="الكل";nationalOnly=true;document.querySelectorAll(".mode").forEach(x=>x.classList.toggle("active",x.dataset.mode==="saudi"));chips();render();window.scrollTo({top:document.querySelector(".controls").offsetTop-20,behavior:"smooth"})};

try{
  const r=await fetch("./data/deals.json",{cache:"no-store"});
  const d=await r.json();
  all=Array.isArray(d.deals)?d.deals:[];
  const saudi=all.filter(x=>channel(x)==="saudi").length;
  const global=all.filter(x=>channel(x)==="global").length;
  const seasonal=all.filter(x=>x.seasonalCampaign==="saudi-national-day-96").length;
  $("#dealCount").textContent=`${all.length} عرض موثق`;
  $("#saudiCount").textContent=`${saudi} عرض • شركات ومحلات ومتاجر وخدمات`;
  $("#globalCount").textContent=`${global} عرض • متاجر عالمية تشحن للسعودية`;
  $("#updatedAt").textContent=`آخر تحديث: ${d.generatedAt?new Date(d.generatedAt).toLocaleString("ar-SA"):"لم يعمل بعد"}`;
  if(d.nationalDayActive||seasonal>0){$("#nationalDay").hidden=false;$("#nationalDay span").textContent=seasonal?`${seasonal} عرض موثق حاليًا • من المتاجر نفسها`:"الرصد الموسمي نشط الآن وسيعرض العروض فور توثيقها"}
  chips();render();
}catch{
  $("#empty").hidden=false;$("#empty").textContent="تعذر تحميل بيانات الرادار.";
}
