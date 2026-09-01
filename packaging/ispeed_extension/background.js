const ISPEED_HOST = "ispeed.extra.chrysler.com";

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !isISpeedUrl(tab.url)) {
    await chrome.tabs.create({
      url: chrome.runtime.getURL("dashboard.html?error=Open%20this%20from%20the%20iSpeed%20results%20page")
    });
    return;
  }

  const url = chrome.runtime.getURL(`dashboard.html?sourceTabId=${tab.id}`);
  await chrome.tabs.create({ url });
});

function isISpeedUrl(url = "") {
  try {
    return new URL(url).hostname === ISPEED_HOST;
  } catch {
    return false;
  }
}
