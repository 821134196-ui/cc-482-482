// 陶艺窑炉排期系统前端脚本：温度轮询、冷却倒计时、照片上传
(function () {
  "use strict";

  // ---- 窑温轮询：data-temp-kiln="<kiln_id>" ----
  var tempEls = Array.prototype.slice.call(document.querySelectorAll("[data-temp-kiln]"));
  function pollTemp() {
    tempEls.forEach(function (el) {
      var kilnId = el.getAttribute("data-temp-kiln");
      fetch("/api/kiln/" + kilnId + "/temp")
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) return;
          var num = el.querySelector(".temp-num");
          var phase = el.querySelector(".temp-phase");
          if (num) num.textContent = d.temp.toFixed(0);
          if (phase) phase.textContent = d.phase + (d.batch_name ? " · " + d.batch_name : "");
        })
        .catch(function () {});
    });
  }
  if (tempEls.length) {
    pollTemp();
    setInterval(pollTemp, 2000);
  }

  // ---- 冷却倒计时：data-cooled-at="<ISO>" ----
  var coolEls = Array.prototype.slice.call(document.querySelectorAll("[data-cooled-at]"));
  function tickCooling() {
    var now = new Date();
    coolEls.forEach(function (el) {
      var target = new Date(el.getAttribute("data-cooled-at"));
      var remain = Math.max(0, target - now);
      var h = Math.floor(remain / 3600000);
      var m = Math.floor((remain % 3600000) / 60000);
      var s = Math.floor((remain % 60000) / 1000);
      var b = el.querySelector("b");
      if (b) b.textContent = remain <= 0 ? "已可开窑" : h + "时 " + m + "分 " + s + "秒";
    });
  }
  if (coolEls.length) {
    tickCooling();
    setInterval(tickCooling, 1000);
  }

  // ---- 干燥剩余时间：data-countdown-hours ----
  var dryEls = Array.prototype.slice.call(document.querySelectorAll("[data-countdown-hours]"));
  function tickDry() {
    dryEls.forEach(function (el) {
      var hours = parseFloat(el.getAttribute("data-countdown-hours"));
      var target = el._target || (el._target = Date.now() + hours * 3600000);
      var remain = Math.max(0, target - Date.now());
      var h = Math.floor(remain / 3600000);
      var m = Math.floor((remain % 3600000) / 60000);
      el.textContent = remain <= 0 ? "可确认（刷新页面）" : "还需 " + h + "时" + m + "分";
    });
  }
  if (dryEls.length) {
    tickDry();
    setInterval(tickDry, 30000);
  }

  // ---- 照片上传：原始字节 POST，避免 multipart ----
  Array.prototype.forEach.call(document.querySelectorAll("[data-upload-photo]"), function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById("photo-file");
      if (!input || !input.files || !input.files.length) {
        alert("请先选择照片文件");
        return;
      }
      var file = input.files[0];
      var params = "kind=" + encodeURIComponent(btn.getAttribute("kind") || "loading");
      if (btn.getAttribute("work-id")) params += "&work_id=" + btn.getAttribute("work-id");
      if (btn.getAttribute("batch-id")) params += "&batch_id=" + btn.getAttribute("batch-id");
      params += "&filename=" + encodeURIComponent(file.name);
      btn.disabled = true;
      fetch("/photos/upload?" + params, { method: "POST", body: file })
        .then(function (r) { return r.json(); })
        .then(function () { location.reload(); })
        .catch(function () {
          alert("上传失败");
          btn.disabled = false;
        });
    });
  });
})();
