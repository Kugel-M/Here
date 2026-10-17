/* Only public UI assets are cached. Photos, credentials, maps and poses never are. */
'use strict';
const CACHE='here-shell-v2';
const ASSETS=['/','/mobile.css','/mobile.js','/navigation.css','/navigation.js','/app.webmanifest','/icons/app-192.png','/icons/app-512.png','/icons/app.svg'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('here-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;
 // Never cache navigation URLs containing an access code. Cache public root instead.
 const key=url.pathname;
 event.respondWith(fetch(event.request).then(response=>{
  if(response.ok&&(key!=='/'||!url.search)){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(key,copy)));}
  return response;
 }).catch(()=>caches.match(key).then(response=>response||Response.error())));
});
