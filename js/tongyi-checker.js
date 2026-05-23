window.addEventListener('DOMContentLoaded', function () {
  var isSupported = true;
  var unSupportReason = '';
  var ua = navigator.userAgent;
  var isMac = /macintosh/i.test(ua) || false;

  // 检测 IE11 及以下（包括 IE6-10）
  var isIE = false || !!document.documentMode;
  if (isIE) {
    isSupported = false;
    unSupportReason = 'IE';
  } else {
    // 检测 Chrome >= 70
    var chromeMatch = ua.match(/Chrome\/(\d+)/) || ua.match(/CriOS\/(\d+)/);
    if (chromeMatch) {
      var chromeVersion = parseInt(chromeMatch[1], 10);
      isSupported = chromeVersion > 70;
      unSupportReason = isSupported ? '' : 'chrome less than 70 (' + chromeVersion + ')';
    }
    // @ts-ignore
    if (typeof Symbol === 'undefined') {
      isSupported = false;
      unSupportReason = 'not support symbol';
    }
    try {
      new RegExp('\\p{L}', 'u');
    } catch (e) {
      isSupported = false;
      unSupportReason = 'not support unicode property escape ';
    }
  }
  function download() {
    var _window$__itrace;
    var download_url = isMac ? window.HTML_GLOBAL_CONFIG.download.mac : window.HTML_GLOBAL_CONFIG.download.windows;
    window.open(download_url);
    (_window$__itrace = window.__itrace) === null || _window$__itrace === void 0 || _window$__itrace.report({
      category: 401,
      msg: 'download-pc'
    });
  }
  if (!isSupported) {
    var _document$getElementB, _document$getElementB2, _document$getElementB3, _window$__itrace3;
    // 使用纯字符串拼接（ES5 安全）
    var fallbackPage = "\n  <style>\n  body {\n    background: #FFFFFF;\n  }\n  .unsupported-container {\n    position: absolute;\n    top: 50%;\n    left: 50%;\n    transform: translate(-50%, -50%);\n  }\n  .unsupported-container .logo {\n    font-weight: 800;\n    font-size: 48px;\n    margin-bottom: 24px;\n    line-height: 1;\n  }\n  .unsupported-container .logo img {\n    display: inline;\n    height: 40px;\n    margin-right: 12px;\n    vertical-align: -12px;\n  }\n  .unsupported-container {\n    line-height: 26px;\n  }\n  .unsupported-container .desc {\n    font-size: 16px;\n    color: rgba(6, 10, 38, 0.7);\n  }\n  .unsupported-container .solution {\n    font-size: 16px;\n    color: rgba(6, 10, 38, 0.7);\n    margin-bottom: 48px;\n  }\n  .unsupported-container .solution a {\n    font-size: 16px;\n    color: #0011FF;\n  }\n  #download-btn {\n    width: 152px;\n    height: 48px;\n    border-radius: 8px;\n    background: rgba(0, 68, 255, 0.05);\n    color: rgba(0, 17, 255, 1);\n    font-size: 16px;\n  }\n  #download-btn:hover{\n    background: #eceaff;\n  }\n  </style>\n  <div class=\"unsupported-container\">\n    <div class=\"logo\">\n      <img src=\"https://img.alicdn.com/imgextra/i1/O1CN01RzxoVE1wBG2yYv9BC_!!6000000006269-2-tps-344-120.png\">\n    </div>\n    <p class=\"desc\">\u62B1\u6B49\uFF0C\u60A8\u7684\u6D4F\u89C8\u5668\u7248\u672C\u8FC7\u4F4E\uFF0C\u65E0\u6CD5\u6B63\u5E38\u8BBF\u95EE\u5343\u95EE\u3002</p>\n    <p class=\"solution\">\n      \u60A8\u53EF\u4EE5\u901A\u8FC7\n      <a id=\"go-chrome-download\" target=\"_blank\">\u5347\u7EA7\u6D4F\u89C8\u5668</a>\n      \u6216 \n      <a id=\"download-link\">\u4E0B\u8F7D\u5343\u95EE\u7535\u8111\u5BA2\u6237\u7AEF</a>\n      \u7EE7\u7EED\u8BBF\u95EE\uFF0C\u611F\u8C22\u60A8\u7684\u652F\u6301\u3002\n    </p>\n    <button id=\"download-btn\">\u4E0B\u8F7D\u5343\u95EE\u7535\u8111\u7248</button>\n  </div>\n  ";
    document.body.innerHTML = fallbackPage;
    (_document$getElementB = document.getElementById("download-link")) === null || _document$getElementB === void 0 || _document$getElementB.addEventListener("click", download);
    (_document$getElementB2 = document.getElementById("download-btn")) === null || _document$getElementB2 === void 0 || _document$getElementB2.addEventListener("click", download);
    (_document$getElementB3 = document.getElementById("go-chrome-download")) === null || _document$getElementB3 === void 0 || _document$getElementB3.addEventListener("click", function () {
      var _window$__itrace2;
      window.open("https://www.google.cn/chrome/fallback/", "_blank");
      (_window$__itrace2 = window.__itrace) === null || _window$__itrace2 === void 0 || _window$__itrace2.report({
        category: 401,
        msg: 'download-chrome'
      });
    });

    // 上报兜底页面展示
    (_window$__itrace3 = window.__itrace) === null || _window$__itrace3 === void 0 || _window$__itrace3.report({
      category: 401,
      msg: 'show',
      w_bl1: unSupportReason
    });
  }
});