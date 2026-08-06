const allFeed = document.querySelector('#all-feed');
const sourceArchive = document.querySelector('#source-archive');
const updated = document.querySelector('#last-updated');
const refresh = document.querySelector('#refresh');
const refreshStatus = document.querySelector('#refresh-status');
const resultCount = document.querySelector('#result-count');
const sourceResultCount = document.querySelector('#source-result-count');
const archiveSortSelect = document.querySelector('#archive-sort-select');
const archiveBrandSelect = document.querySelector('#archive-brand-select');
const archiveMonthSelect = document.querySelector('#archive-month-select');
const tabs = [...document.querySelectorAll('[role="tab"]')];

let dashboardData = null;
let latestLoadId = 0;
let refreshInProgress = false;
const archiveStartMonth = '2026-01';
const refreshEndpoint = 'https://saffron-signal-desk-refresh.netlify.app/api/refresh';
const refreshPollInterval = 5000;
const refreshWaitLimit = 600000;

function prettyDate(value, withTime = false) {
  if (!value) return withTime ? 'Waiting for first refresh' : 'Date unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function monthLabel(value) {
  const key = monthKey(value);
  if (key === 'unknown') return 'Date unavailable';
  const date = new Date(`${key}-15T12:00:00`);
  return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(date);
}

function monthKey(value) {
  const calendarMatch = String(value || '').match(/^(\d{4})-(\d{2})/);
  if (calendarMatch) return `${calendarMatch[1]}-${calendarMatch[2]}`;
  const date = new Date(value || 0);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

function archiveMonthKeys() {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth() + 1;
  const months = [];

  while (`${year}-${String(month).padStart(2, '0')}` >= archiveStartMonth) {
    months.push(`${year}-${String(month).padStart(2, '0')}`);
    month -= 1;
    if (month === 0) {
      month = 12;
      year -= 1;
    }
  }

  return months;
}

function timestamp(value) {
  const parsed = new Date(value || 0).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function articleDateValue(article) {
  return article.published_at || article.fetched_at;
}

function articleDateLabel(article) {
  const isPublished = Boolean(article.published_at && timestamp(article.published_at));
  return `${isPublished ? 'Published' : 'First seen'} ${prettyDate(articleDateValue(article))}`;
}

function escapeHtml(value = '') {
  const el = document.createElement('div');
  el.textContent = value;
  return el.innerHTML;
}

function safeUrl(value = '') {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol)
      ? url.href.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
      : '#';
  } catch {
    return '#';
  }
}

function articlesWithSources(data) {
  return Object.entries(data.sources).flatMap(([sourceId, source]) =>
    source.articles.map(article => ({
      ...article,
      sourceId,
      sourceName: source.name,
      sourceShort: source.short,
      sourceColor: source.color,
    }))
  );
}

function mainTopic(title = '') {
  const cleaned = title
    .replace(/\([^)]*\)/g, ' ')
    .split(/[:|—–]/)[0]
    .replace(/^\d+\s+/, '')
    .replace(/\s+/g, ' ')
    .trim();
  const words = cleaned.split(' ').filter(Boolean);
  return words.slice(0, 12).join(' ') || 'Marketing and search industry update';
}

function quickSummary(article) {
  const fallback = `This update from ${article.sourceName} explores ${mainTopic(article.title).toLowerCase()}. Read the full article for the complete analysis, examples, and recommendations.`;
  const text = (article.excerpt || fallback).replace(/\s+/g, ' ').trim();
  const words = text.split(' ').filter(Boolean);
  return words.length <= 100 ? text : `${words.slice(0, 100).join(' ').replace(/[.,;:!?]?$/, '')}…`;
}

function articleCard(article) {
  return `
    <article class="feed-card" style="--accent:${article.sourceColor}">
      <div class="feed-card-meta">
        <div class="update-meta"><span class="update-label">Update</span><span class="brand-chip" aria-label="Source: ${escapeHtml(article.sourceName)}"><span class="source-initials" aria-hidden="true">${escapeHtml(article.sourceShort)}</span><span class="source-full-name">${escapeHtml(article.sourceName)}</span></span></div>
        <time datetime="${escapeHtml(articleDateValue(article) || '')}">${articleDateLabel(article)}</time>
      </div>
      <h2><a href="${safeUrl(article.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a></h2>
      <p class="topic-line"><strong>Main topic</strong><span>${escapeHtml(mainTopic(article.title))}</span></p>
      <div class="summary-block"><span class="summary-label">Quick summary</span><p>${escapeHtml(quickSummary(article))}</p></div>
      <a class="read-link" href="${safeUrl(article.url)}" target="_blank" rel="noopener noreferrer" aria-label="Read ${escapeHtml(article.title)} on ${escapeHtml(article.sourceName)}">Read full article <span aria-hidden="true">↗</span></a>
    </article>`;
}

function renderAllFeed() {
  if (!dashboardData) return;
  const articles = articlesWithSources(dashboardData)
    .sort((a, b) => timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));

  resultCount.textContent = `${articles.length} ${articles.length === 1 ? 'article' : 'articles'}`;
  allFeed.setAttribute('aria-busy', 'false');

  if (!articles.length) {
    allFeed.innerHTML = '<div class="empty-state"><strong>No articles found</strong><span>Choose another brand or refresh the dashboard.</span></div>';
    return;
  }

  allFeed.innerHTML = `<div class="feed-list">${articles.map(articleCard).join('')}</div>`;
}

function renderSourceArchive() {
  if (!dashboardData) return;
  const selectedBrand = archiveBrandSelect.value;
  const selectedMonth = archiveMonthSelect.value;
  const sortMode = archiveSortSelect.value;
  let articles = articlesWithSources(dashboardData);

  if (selectedBrand !== 'all') articles = articles.filter(article => article.sourceId === selectedBrand);
  if (selectedMonth !== 'all') articles = articles.filter(article => monthKey(articleDateValue(article)) === selectedMonth);

  if (!articles.length && selectedMonth !== 'all') {
    archiveMonthSelect.value = 'all';
    renderSourceArchive();
    return;
  }

  if (sortMode === 'oldest') {
    articles.sort((a, b) => timestamp(articleDateValue(a)) - timestamp(articleDateValue(b)));
  } else if (sortMode === 'brand') {
    articles.sort((a, b) => a.sourceName.localeCompare(b.sourceName) || timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));
  } else {
    articles.sort((a, b) => timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));
  }

  sourceResultCount.textContent = `${articles.length} ${articles.length === 1 ? 'article' : 'articles'}`;
  sourceArchive.setAttribute('aria-busy', 'false');
  sourceArchive.innerHTML = articles.length
    ? `<div class="feed-list">${articles.map(articleCard).join('')}</div>`
    : '<div class="empty-state"><strong>No matching articles</strong><span>Try another brand or release month.</span></div>';
}

function populateBrands() {
  const currentValue = archiveBrandSelect.value;
  archiveBrandSelect.innerHTML = '<option value="all">All brands</option>' + Object.entries(dashboardData.sources)
    .map(([id, source]) => `<option value="${escapeHtml(id)}">${escapeHtml(source.name)}</option>`)
    .join('');
  archiveBrandSelect.value = [...archiveBrandSelect.options].some(option => option.value === currentValue) ? currentValue : 'all';
}

function populateMonths() {
  const currentValue = archiveMonthSelect.value;
  const selectedBrand = archiveBrandSelect.value;
  const brandArticles = articlesWithSources(dashboardData)
    .filter(article => selectedBrand === 'all' || article.sourceId === selectedBrand);
  const availableMonths = new Set(brandArticles
    .map(article => monthKey(articleDateValue(article)))
    .filter(value => value !== 'unknown'));
  archiveMonthSelect.innerHTML = '<option value="all">All months</option>' + archiveMonthKeys()
    .map(value => `<option value="${escapeHtml(value)}"${availableMonths.has(value) ? '' : ' disabled'}>${escapeHtml(monthLabel(value))}</option>`)
    .join('');
  archiveMonthSelect.value = [...archiveMonthSelect.options]
    .some(option => option.value === currentValue && !option.disabled) ? currentValue : 'all';
}

function render(data) {
  dashboardData = data;
  updated.textContent = prettyDate(data.last_updated, true);
  populateBrands();
  populateMonths();
  renderAllFeed();
  renderSourceArchive();
}

function selectView(view, focus = false) {
  tabs.forEach(tab => {
    const active = tab.dataset.view === view;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  });
  document.querySelector('#panel-all').hidden = view !== 'all';
  document.querySelector('#panel-sources').hidden = view !== 'sources';
  history.replaceState(null, '', view === 'sources' ? '#sources' : '#all');
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectView(tab.dataset.view));
  tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    selectView(tabs[next].dataset.view, true);
  });
});

archiveSortSelect.addEventListener('change', renderSourceArchive);
archiveBrandSelect.addEventListener('change', () => {
  populateMonths();
  renderSourceArchive();
});
archiveMonthSelect.addEventListener('change', renderSourceArchive);

function dashboardSignature(data) {
  if (!data) return '';
  const articleCount = Object.values(data.sources || {})
    .reduce((total, source) => total + (source.articles?.length || 0), 0);
  return `${data.last_updated || ''}:${articleCount}`;
}

function wait(milliseconds) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

async function waitForPublishedRefresh(previousSignature) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < refreshWaitLimit) {
    await wait(refreshPollInterval);
    const data = await load();
    if (dashboardSignature(data) !== previousSignature) return data;
  }
  throw new Error('The update is still running. The dashboard will check again when you return.');
}

async function load() {
  const loadId = ++latestLoadId;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 15000);
  const dataUrl = new URL('./data/articles.json', window.location.href);
  dataUrl.searchParams.set('v', `${Date.now()}-${loadId}`);
  try {
    const response = await fetch(dataUrl, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error('Could not load articles');
    const data = await response.json();
    if (loadId === latestLoadId) render(data);
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Refresh timed out');
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

refresh.addEventListener('click', async () => {
  if (refreshInProgress) return;

  refreshInProgress = true;
  const label = refresh.querySelector('span:last-child');
  const previousSignature = dashboardSignature(dashboardData);
  refresh.disabled = true;
  refresh.classList.add('busy');
  refresh.setAttribute('aria-busy', 'true');
  label.textContent = 'Refreshing…';
  refreshStatus.textContent = 'Checking for the latest published articles.';

  try {
    const response = await fetch(refreshEndpoint, {
      method: 'POST',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: '{}',
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.message || 'Refresh could not start');

    if (result.status === 'recent') {
      const data = await load();
      label.textContent = 'Up to date';
      refreshStatus.textContent = `Dashboard is already up to date. Latest data refresh: ${prettyDate(data.last_updated, true)}.`;
    } else {
      label.textContent = 'Updating sources…';
      refreshStatus.textContent = 'Collecting every monitored source and publishing the latest articles.';
      const data = await waitForPublishedRefresh(previousSignature);
      label.textContent = 'Updated';
      refreshStatus.textContent = `Dashboard updated. Latest data refresh: ${prettyDate(data.last_updated, true)}.`;
    }
  } catch (error) {
    label.textContent = 'Try again';
    refreshStatus.textContent = `${error.message}. The current articles remain available.`;
  } finally {
    window.setTimeout(() => {
      refresh.disabled = false;
      refresh.classList.remove('busy');
      refresh.removeAttribute('aria-busy');
      label.textContent = 'Refresh';
      refreshInProgress = false;
    }, 900);
  }
});

window.addEventListener('focus', () => {
  if (!refreshInProgress) load().catch(() => {});
});


selectView(location.hash === '#sources' ? 'sources' : 'all');
load().catch(error => {
  allFeed.innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
  sourceArchive.innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
});

