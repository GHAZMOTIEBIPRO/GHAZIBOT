import assert from "node:assert/strict";
import {extractGenericProduct,mergeDefined} from "./generic-product.mjs";

const html=`<!doctype html><html><head>
<meta property="og:title" content="حذاء تجريبي">
<meta property="og:image" content="/media/shoe.jpg">
<meta property="product:price:amount" content="149.50">
<meta property="product:price:currency" content="SAR">
<link rel="canonical" href="https://shop.test/product/shoe">
</head><body><div class="old-price">199 ريال</div><button>أضف للسلة</button></body></html>`;
const p=extractGenericProduct(html,{sourceKey:"shop",pageUrl:"https://shop.test/product/shoe?utm_source=x",fallbackTitle:"fallback"});
assert.equal(p.title,"حذاء تجريبي");
assert.equal(p.currentPrice,149.5);
assert.equal(p.previousPrice,199);
assert.equal(p.currency,"SAR");
assert.equal(p.productUrl,"https://shop.test/product/shoe");
assert.equal(p.imageUrl,"https://shop.test/media/shoe.jpg");
assert.equal(p.availability,"in_stock");
const merged=mergeDefined({currentPrice:100,imageUrl:"a"},{currentPrice:null,imageUrl:""},{title:"X"});
assert.equal(merged.currentPrice,100);assert.equal(merged.imageUrl,"a");assert.equal(merged.title,"X");
console.log("GENERIC_PRODUCT_TEST_OK");
