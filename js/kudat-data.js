import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import DOMPurify from 'https://esm.sh/dompurify@3';
import { KUDAT_CONFIG } from './config.js';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const selectedArticleIds = new Set();
let supabase = null;

const KIND_LABELS = {
  person: '인물', organization: '조직', place: '장소', event: '사건',
  culture: '문화', policy_program: '정책·프로그램', document: '문서', article: '기사'
};

const GROUP_MAP = {
  person: 'person', organization: 'org', place: 'space', event: 'event',
  culture: 'culture', policy_program: 'event', document: 'culture', article: 'article'
};

const GROUP_STYLES = {
  article: { shape: 'box', color: { background: '#fee2e2', border: '#ef4444' }, font: { color: '#991b1b', size: 11, face: 'Pretendard' } },
  person: { shape: 'dot', size: 17, color: { background: '#3b82f6', border: '#1d4ed8' }, font: { color: '#1e3a8a', size: 11, face: 'Pretendard' } },
  org: { shape: 'dot', size: 18, color: { background: '#a855f7', border: '#7e22ce' }, font: { color: '#581c87', size: 11, face: 'Pretendard' } },
  space: { shape: 'dot', size: 18, color: { background: '#10b981', border: '#047857' }, font: { color: '#064e3b', size: 11, face: 'Pretendard' } },
  event: { shape: 'dot', size: 19, color: { background: '#f59e0b', border: '#b45309' }, font: { color: '#78350f', size: 11, face: 'Pretendard' } },
  culture: { shape: 'dot', size: 17, color: { background: '#06b6d4', border: '#0891b2' }, font: { color: '#164e63', size: 11, face: 'Pretendard' } }
};

function showStatus(message, tone = 'info') {
  const element = $('#dataStatus');
  if (!element) return;
  const tones = {
    info: 'bg-blue-50 text-blue-800 border-blue-200',
    ok: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    warn: 'bg-amber-50 text-amber-900 border-amber-200',
    error: 'bg-red-50 text-red-800 border-red-200'
  };
  element.className = `shrink-0 px-4 py-2 text-center text-[11px] font-bold border-b z-30 ${tones[tone]}`;
  element.textContent = message;
}

function formatDate(value) {
  if (!value) return '';
  const [year, month, day] = value.split('-');
  return `${year}.${month}.${day}`;
}

function createTextElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text || '';
  return element;
}

function createArticleRow(article, { showCheckbox = false } = {}) {
  const row = document.createElement('article');
  row.className = 'p-4 sm:p-5 hover:bg-slate-50 transition flex gap-3';

  if (showCheckbox) {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'mt-1 rounded text-crimson-800 focus:ring-crimson-800';
    checkbox.checked = selectedArticleIds.has(Number(article.id));
    checkbox.setAttribute('aria-label', `${article.title} 관계망 선택`);
    checkbox.addEventListener('change', () => {
      const id = Number(article.id);
      checkbox.checked ? selectedArticleIds.add(id) : selectedArticleIds.delete(id);
      updateGraphButton();
    });
    row.appendChild(checkbox);
  }

  const content = document.createElement('div');
  content.className = 'min-w-0 flex-1';
  const meta = [formatDate(article.published_on), article.primary_section_name, article.secondary_section_name, article.author_name]
    .filter(Boolean).join(' · ');
  content.appendChild(createTextElement('div', 'text-[11px] font-bold text-crimson-800 mb-1', meta));

  const titleButton = createTextElement('button', 'text-left text-sm sm:text-base font-black text-slate-900 hover:text-crimson-800 transition', article.title);
  titleButton.addEventListener('click', () => openArticle(article.id));
  content.appendChild(titleButton);
  if (article.subtitle) content.appendChild(createTextElement('p', 'text-xs text-slate-600 mt-1', article.subtitle));
  if (article.snippet) content.appendChild(createTextElement('p', 'text-xs text-slate-500 mt-2 line-clamp-2', article.snippet));

  const actions = document.createElement('div');
  actions.className = 'mt-2 flex flex-wrap gap-2';
  const openButton = createTextElement('button', 'text-[11px] font-bold text-crimson-800 hover:underline', '기사 읽기 ➔');
  openButton.addEventListener('click', () => openArticle(article.id));
  actions.appendChild(openButton);
  actions.appendChild(createTextElement('span', 'text-[11px] font-bold text-slate-500', 'XLSX 수록 기사'));
  content.appendChild(actions);
  row.appendChild(content);
  return row;
}

function updateGraphButton() {
  const button = $('#openSelectedGraphButton');
  if (!button) return;
  button.classList.toggle('hidden', selectedArticleIds.size === 0);
  button.textContent = `선택 ${selectedArticleIds.size}건 관계망 보기`;
}

async function runSearch() {
  if (!supabase) {
    showStatus('먼저 js/config.js에 Supabase URL과 publishable 키를 입력하세요.', 'warn');
    return;
  }
  const button = $('#searchButton');
  button.disabled = true;
  button.classList.add('opacity-60');
  const terms = [];
  const ops = [];
  $$('.boolean-term').forEach((input, index) => {
    const value = input.value.trim();
    if (value) {
      terms.push(value);
      ops.push($$('.boolean-op')[index].value);
    }
  });
  const excludeFrom = $('#excludeFrom').value || null;
  const excludeTo = $('#excludeTo').value || null;
  if ((excludeFrom && !excludeTo) || (!excludeFrom && excludeTo)) {
    showStatus('제외 일자는 시작일과 종료일을 모두 입력해야 합니다.', 'warn');
    button.disabled = false;
    button.classList.remove('opacity-60');
    return;
  }

  const panel = $('#searchResultsPanel');
  const list = $('#searchResultsList');
  panel.classList.remove('hidden');
  list.replaceChildren(createTextElement('div', 'p-8 text-center text-xs text-slate-500', '검색 중…'));
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const { data, error } = await supabase.rpc('search_articles', {
    p_main: $('#homeSearchInput').value.trim(),
    p_terms: terms,
    p_ops: ops,
    p_from: $('#dateFrom').value || null,
    p_to: $('#dateTo').value || null,
    p_exclude_from: excludeFrom,
    p_exclude_to: excludeTo,
    p_section: $('#sectionFilter').value || null,
    p_scope: $('#searchScope').value,
    p_limit: 50,
    p_offset: 0
  });

  button.disabled = false;
  button.classList.remove('opacity-60');
  if (error) {
    list.replaceChildren(createTextElement('div', 'p-8 text-center text-xs text-red-700', `검색 오류: ${error.message}`));
    showStatus('검색 RPC 실행에 실패했습니다. SQL 마이그레이션과 RLS 설정을 확인하세요.', 'error');
    return;
  }
  const total = data?.[0]?.total_count || 0;
  $('#searchResultsSummary').textContent = `총 ${Number(total).toLocaleString('ko-KR')}건 중 최대 50건 표시`;
  list.replaceChildren();
  if (!data?.length) {
    list.appendChild(createTextElement('div', 'p-8 text-center text-xs text-slate-500', '조건에 맞는 기사가 없습니다.'));
    return;
  }
  data.forEach(article => list.appendChild(createArticleRow(article, { showCheckbox: true })));
}

async function openArticle(articleId) {
  if (!supabase) return;
  showStatus('기사와 엔터티를 불러오는 중입니다…', 'info');
  const { data, error } = await supabase
    .from('articles')
    .select(`id,title,subtitle,author_name,published_on,primary_section_name,secondary_section_name,body_html,article_entity_mentions(surface_text,confidence,entity:entities(id,kind,canonical_name))`)
    .eq('id', articleId)
    .single();
  if (error) {
    showStatus(`기사 조회 실패: ${error.message}`, 'error');
    return;
  }

  $('#viewerLegacyScanPanel')?.classList.add('hidden');
  $('#viewerTextModeControls')?.classList.add('hidden');
  const articlePanel = $('#viewerArticlePanel');
  if (articlePanel) articlePanel.className = 'w-full bg-white flex flex-col overflow-y-auto scrollbar-custom';
  $('#viewerArticleTitle').textContent = data.title;
  $('#viewerTopDate').textContent = formatDate(data.published_on);
  const section = [data.primary_section_name, data.secondary_section_name].filter(Boolean).join(' · ') || '기사';
  $('#viewerTopSection').textContent = section;
  $('#viewerSectionBadge').textContent = section;

  const meta = $('#viewerArticleMeta');
  meta.replaceChildren();
  meta.appendChild(createTextElement('span', '', `발행: ${formatDate(data.published_on)}`));
  if (data.author_name) meta.appendChild(createTextElement('span', '', `취재: ${data.author_name}`));
  if (data.subtitle) meta.appendChild(createTextElement('span', 'w-full mt-1 text-slate-700', data.subtitle));

  const body = $('#articleContent');
  body.innerHTML = DOMPurify.sanitize(data.body_html || '', {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['script', 'style', 'iframe', 'img', 'form', 'object', 'embed', 'svg', 'math'],
    FORBID_ATTR: ['style', 'href', 'src', 'srcset', 'target', 'rel']
  });

  const badges = $('#viewerEntityBadges');
  badges.replaceChildren();
  const seen = new Set();
  const mentions = (data.article_entity_mentions || []).filter(item => item.entity);
  mentions.forEach(item => {
    if (seen.has(item.entity.id)) return;
    seen.add(item.entity.id);
    const badge = createTextElement(
      'button',
      'bg-white border border-crimson-200 px-2 py-1 rounded-lg font-bold hover:bg-crimson-50 transition',
      `[${KIND_LABELS[item.entity.kind] || item.entity.kind}] ${item.entity.canonical_name}`
    );
    badge.addEventListener('click', () => loadGraph([Number(data.id)]));
    badges.appendChild(badge);
  });
  if (!seen.size) badges.appendChild(createTextElement('span', 'text-slate-500', '승인된 엔터티가 없습니다.'));
  selectedArticleIds.add(Number(data.id));
  updateGraphButton();
  window.navigateTo('viewer');
  showStatus(`XLSX 수록 기사 #${data.id}를 표시 중입니다.`, 'ok');
}

function styleGraphNode(raw) {
  const group = GROUP_MAP[raw.group] || 'culture';
  return { ...raw, group, ...GROUP_STYLES[group] };
}

function graphDetails(nodes, edges) {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const details = {};
  nodes.forEach(node => {
    const neighbors = edges.filter(edge => edge.from === node.id || edge.to === node.id).slice(0, 30).map(edge => {
      const neighbor = byId.get(edge.from === node.id ? edge.to : edge.from);
      return { name: neighbor?.label || '알 수 없음', type: KIND_LABELS[neighbor?.rawKind] || neighbor?.group || '엔터티', relation: edge.label };
    });
    details[node.id] = {
      type: KIND_LABELS[node.rawKind] || KIND_LABELS[node.group] || '엔터티',
      badgeClass: 'bg-crimson-100 text-crimson-900',
      title: node.label,
      sub: node.publishedOn ? `발행일 ${formatDate(node.publishedOn)}` : `연결 기사 ${node.articleCount || 0}건`,
      desc: node.description || '승인된 기사 멘션과 관계를 바탕으로 구성된 엔터티입니다.',
      neighbors,
      articles: node.articleId ? [{ num: formatDate(node.publishedOn), title: node.label, articleId: node.articleId }] : []
    };
  });
  return details;
}

async function loadGraph(articleIds = [...selectedArticleIds]) {
  if (!supabase || !articleIds.length) {
    showStatus('관계망으로 볼 기사를 한 건 이상 선택하세요.', 'warn');
    return;
  }
  showStatus(`선택 기사 ${articleIds.length}건의 관계망을 구성 중입니다…`, 'info');
  const { data, error } = await supabase.rpc('get_article_graph', {
    p_article_ids: articleIds.map(Number),
    p_min_confidence: 0.85,
    p_include_cooccurrence: true,
    p_max_entities: 120
  });
  if (error) {
    showStatus(`관계망 조회 실패: ${error.message}`, 'error');
    return;
  }
  const nodes = (data?.nodes || []).map(raw => {
    const styled = styleGraphNode(raw);
    styled.rawKind = raw.group;
    return styled;
  });
  const edges = (data?.edges || []).map(raw => ({
    ...raw,
    color: { color: raw.kind === 'semantic' ? '#7e22ce' : raw.kind === 'cooccurrence' ? '#94a3b8' : '#ef4444' },
    dashes: raw.kind === 'cooccurrence',
    arrows: raw.kind === 'semantic' ? 'to' : undefined,
    width: Math.min(1 + Number(raw.weight || 1) * 0.35, 5)
  }));
  const articles = nodes.filter(node => node.group === 'article').map(node => ({
    id: node.id,
    articleId: node.articleId,
    title: node.label,
    date: formatDate(node.publishedOn),
    issue: '온라인 기사',
    tag: '실데이터'
  }));
  window.kudatApplyGraphData({ articles, nodes, edges, details: graphDetails(nodes, edges) });
  window.navigateTo('graph');
  showStatus(`관계망: 기사 ${data.articleCount || 0}건 · 엔터티 ${data.entityCount || 0}개${data.truncated ? ' (상위 120개 표시)' : ''}`, 'ok');
}

function updateBirthDays() {
  const year = Number($('#birthYear').value);
  const month = Number($('#birthMonth').value);
  const daySelect = $('#birthDay');
  const previous = Number(daySelect.value) || 1;
  const count = new Date(year, month, 0).getDate();
  daySelect.replaceChildren();
  for (let day = 1; day <= count; day += 1) {
    const option = new Option(String(day), String(day), false, day === Math.min(previous, count));
    daySelect.add(option);
  }
}

async function searchBirthday() {
  if (!supabase) {
    showStatus('먼저 Supabase 연결 정보를 입력하세요.', 'warn');
    return;
  }
  const year = $('#birthYear').value;
  const month = String($('#birthMonth').value).padStart(2, '0');
  const day = String($('#birthDay').value).padStart(2, '0');
  const targetDate = `${year}-${month}-${day}`;
  const card = $('#birthdayResultCard');
  const list = $('#birthdayResultsList');
  card.classList.remove('hidden');
  $('#birthdayResultTitle').textContent = `고대신문 ${formatDate(targetDate)}`;
  $('#birthdayNearestDates').textContent = '';
  list.replaceChildren(createTextElement('div', 'p-8 text-center text-xs text-slate-500', '기사를 찾는 중…'));

  const { data, error } = await supabase.rpc('articles_on_date', { p_date: targetDate });
  if (error) {
    list.replaceChildren(createTextElement('div', 'p-8 text-center text-xs text-red-700', `조회 오류: ${error.message}`));
    return;
  }
  list.replaceChildren();
  if (data?.length) {
    data.forEach(article => list.appendChild(createArticleRow(article, { showCheckbox: true })));
    $('#birthdayNearestDates').textContent = `이 날짜에 발행된 온라인 기사 ${data.length}건`;
  } else {
    list.appendChild(createTextElement('div', 'p-8 text-center text-xs text-slate-500', '이 날짜에 발행된 온라인 기사가 없습니다.'));
    const nearest = await supabase.rpc('nearest_publication_dates', { p_date: targetDate });
    if (!nearest.error && nearest.data?.length) {
      $('#birthdayNearestDates').textContent = nearest.data.map(item =>
        `${item.direction === 'previous' ? '이전' : '다음'} 발행일 ${formatDate(item.published_on)} (${item.article_count}건)`
      ).join(' · ');
    }
  }
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function configureControls() {
  $('#dateFrom').min = KUDAT_CONFIG.dataMinDate;
  $('#dateFrom').max = KUDAT_CONFIG.dataMaxDate;
  $('#dateTo').min = KUDAT_CONFIG.dataMinDate;
  $('#dateTo').max = KUDAT_CONFIG.dataMaxDate;

  const yearSelect = $('#birthYear');
  if (yearSelect) {
    yearSelect.replaceChildren();
    const minYear = Number(KUDAT_CONFIG.dataMinDate.slice(0, 4));
    const maxYear = Number(KUDAT_CONFIG.dataMaxDate.slice(0, 4));
    for (let year = minYear; year <= maxYear; year += 1) yearSelect.add(new Option(String(year), String(year)));
    yearSelect.value = String(minYear);
  }
  const monthSelect = $('#birthMonth');
  if (monthSelect) {
    monthSelect.replaceChildren();
    for (let month = 1; month <= 12; month += 1) monthSelect.add(new Option(String(month), String(month)));
    monthSelect.value = '1';
  }
  updateBirthDays();
  $('#birthYear')?.addEventListener('change', updateBirthDays);
  $('#birthMonth')?.addEventListener('change', updateBirthDays);
  $('#searchButton')?.addEventListener('click', runSearch);
  $('#homeSearchInput')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') runSearch();
  });
  $('#birthdaySearchButton')?.addEventListener('click', searchBirthday);
  $('#openSelectedGraphButton')?.addEventListener('click', () => loadGraph());
}

async function initialize() {
  configureControls();
  window.kudatApplyGraphData?.({ articles: [], nodes: [], edges: [], details: {} });
  $('#viewerLegacyScanPanel')?.classList.add('hidden');
  $('#viewerTextModeControls')?.classList.add('hidden');
  const panel = $('#viewerArticlePanel');
  if (panel) panel.className = 'w-full bg-white flex flex-col overflow-y-auto scrollbar-custom';
  $('#articleContent').replaceChildren(createTextElement('p', 'text-center text-slate-500 py-12', '검색 결과에서 기사를 선택하면 실제 본문이 표시됩니다.'));

  if (!KUDAT_CONFIG.supabaseUrl || !KUDAT_CONFIG.supabasePublishableKey) {
    showStatus('Supabase 미연결: js/config.js에 프로젝트 URL과 publishable 키를 입력하면 실데이터 기능이 활성화됩니다.', 'warn');
    return;
  }
  supabase = createClient(KUDAT_CONFIG.supabaseUrl, KUDAT_CONFIG.supabasePublishableKey, {
    auth: { persistSession: false, autoRefreshToken: false }
  });
  const { count, error } = await supabase.from('articles').select('id', { count: 'exact', head: true });
  if (error) {
    showStatus(`Supabase 연결 실패: ${error.message}`, 'error');
  } else {
    showStatus(`Supabase 실데이터 연결됨 · 공개 기사 ${Number(count || 0).toLocaleString('ko-KR')}건`, 'ok');
  }
}

window.kudatOpenArticle = openArticle;
initialize();
