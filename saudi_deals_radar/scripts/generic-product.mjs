import {cleanText,normalizeUrl,parseNumber,extractBestImage,extractPreviousPriceFromText,inferAvailability} from "./core.mjs";

function attrValue(attrs,name){const m=String(attrs||"").match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`,`i`));return m?.[1]||null}
function metaContent(html,key){for(const m of String(html||"").matchAll(/<meta\b([^>]+)>/gi)){const a=m[1],k=attrValue(a,"property")||attrValue(a,"name")||attrValue(a,"itemprop");if(String(k||"").toLowerCase()===String(key).toLowerCase())return attrValue(a,"content")}return null}
function firstMatch(html,patterns){for(const rx of patterns){const m=String(html||"").match(rx);if(m?.[1])return m[1]}return null}
function nonEmpty(v){return v!==undefined&&v!==null&&v!==""}

export function extractGenericProduct(html,{sourceKey,pageUrl,fallbackTitle=""}={}){
  const body=String(html||"");
  const title=cleanText(metaContent(body,"og:title")||metaContent(body,"twitter:title")||firstMatch(body,[/<h1\b[^>]*>([\s\S]{1,500}?)<\/h1>/i,/<title\b[^>]*>([\s\S]{1,500}?)<\/title>/i])||fallbackTitle);
  const canonical=firstMatch(body,[/<link\b[^>]*rel=["']canonical["'][^>]*href=["']([^"']+)["']/i,/<link\b[^>]*href=["']([^"']+)["'][^>]*rel=["']canonical["']/i]);
  const productUrl=normalizeUrl(canonical||pageUrl,pageUrl)||pageUrl;
  const currency=metaContent(body,"product:price:currency")||metaContent(body,"priceCurrency")||firstMatch(body,[/"priceCurrency"\s*:\s*"([A-Z]{3})"/i])||"SAR";
  const rawPrice=metaContent(body,"product:price:amount")||metaContent(body,"price")||firstMatch(body,[/itemprop=["']price["'][^>]*(?:content|value)=["']([\d.,]+)["']/i,/(?:content|value)=["']([\d.,]+)["'][^>]*itemprop=["']price["']/i,/data-price-amount=["']([\d.,]+)["']/i,/"(?:currentPrice|current_price|salePrice|sale_price|specialPrice|special_price|finalPrice|final_price|discountedPrice|discounted_price)"\s*:\s*"?([\d.,]+)"?/i]);
  const currentPrice=parseNumber(rawPrice);
  const imageUrl=extractBestImage(body,pageUrl,title);
  const sku=metaContent(body,"product:retailer_item_id")||metaContent(body,"sku")||firstMatch(body,[/"sku"\s*:\s*"([^"]+)"/i,/data-product-sku=["']([^"']+)["']/i]);
  const availability=inferAvailability(body,"unknown");
  const previousPrice=currentPrice?extractPreviousPriceFromText(body,currentPrice):null;
  const out={sourceKey,sourcePageUrl:pageUrl,title,productUrl,imageUrl,currentPrice,previousPrice,currency,availability,sku,metadata:{genericFallback:true}};
  return Object.fromEntries(Object.entries(out).filter(([,v])=>nonEmpty(v)));
}

export function mergeDefined(...objects){const out={};for(const obj of objects){for(const [k,v] of Object.entries(obj||{})){if(nonEmpty(v))out[k]=v}}return out}
