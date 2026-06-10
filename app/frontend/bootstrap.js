/* Fetch the live data contract from the backend, expose it as window.DATA, then load the
   console app (app.js renders from window.DATA). Keeps the approved UI; swaps fake data
   for real validated results. */
(function () {
  "use strict";
  var API = (window.WONDER_API_BASE || "") + "/api";
  window.WONDER_API = API;
  fetch(API + "/bootstrap")
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (data) {
      window.DATA = data;
      var s = document.createElement("script");
      s.src = "app.js";
      document.body.appendChild(s);
    })
    .catch(function (e) {
      document.body.innerHTML =
        '<div style="padding:48px;max-width:680px;margin:40px auto;font-family:system-ui;' +
        'background:#131722;color:#e6e9f0;border:1px solid #2a2f3d;border-radius:12px">' +
        '<h2 style="margin:0 0 10px">Couldn’t reach the API</h2>' +
        '<p style="color:#9aa3b5">' + e + '</p>' +
        '<p style="color:#9aa3b5">Start the backend and seed it, then reload:</p>' +
        '<pre style="background:#0b0e16;border:1px solid #2a2f3d;border-radius:8px;padding:12px;color:#c8d3ec">' +
        './run.sh</pre></div>';
    });
})();
