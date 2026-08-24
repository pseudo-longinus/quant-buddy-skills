const ALL_VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 1000, mobile: false },
  { name: 'mobile390', width: 390, height: 844, mobile: true },
  { name: 'mobile320', width: 320, height: 720, mobile: true },
];

// 控制台核心错误判定：queryDataGrant/queryFormulaPackage 等 CORS、mixed-content、Failed to fetch、
// 运行时异常都算阻塞性核心错误；但平台注入的 /webapi/skill/track 分析埋点是 fire-and-forget，
// 本地 file://(origin=null) 与跨子域验收都会因后端未回 CORS 头失败，不是数据接口，降为非核心告警。
export const CORE_ERROR_RE = /queryFormulaPackage|CORS|mixed-content|Failed to fetch|ReferenceError|TypeError/i;
export const TRACKER_NOISE_RE = /\/webapi\/skill\/track\b|\/skill\/track\b/;

export function isCoreConsoleError(text) {
  const s = String(text || '');
  return CORE_ERROR_RE.test(s) && !TRACKER_NOISE_RE.test(s);
}

const PROFILES = {
  full: {
    viewports: ALL_VIEWPORTS,
    checkLayout: true,
    cardRuntimeOnly: false,
  },
  'fork-local': {
    viewports: [ALL_VIEWPORTS[0], ALL_VIEWPORTS[2]],
    checkLayout: true,
    cardRuntimeOnly: false,
  },
  'public-smoke': {
    viewports: [{ name: 'publicSmoke', width: 1280, height: 800, mobile: false }],
    checkLayout: false,
    cardRuntimeOnly: false,
  },
  'ui-refinement': {
    viewports: ALL_VIEWPORTS,
    checkLayout: true,
    checkShareModal: true,
    cardRuntimeOnly: false,
  },
  'live-only': {
    viewports: [],
    checkLayout: false,
    cardRuntimeOnly: true,
  },
};

export function resolveVerificationProfile(name = 'full') {
  const normalized = String(name || 'full').trim().toLowerCase();
  const profile = PROFILES[normalized];
  if (!profile) {
    const error = new Error(`unknown verification profile: ${name}`);
    error.code = 'UNKNOWN_VERIFICATION_PROFILE';
    throw error;
  }
  return {
    name: normalized,
    viewports: profile.viewports.map(viewport => ({ ...viewport })),
    checkLayout: profile.checkLayout,
    checkShareModal: profile.checkShareModal === true,
    cardRuntimeOnly: profile.cardRuntimeOnly,
  };
}

export function parseExtraViewport(value, index = 1) {
  const text = String(value || '').trim();
  const match = text.match(/^(?:([a-zA-Z][a-zA-Z0-9_-]{0,31}):)?(\d{2,4})x(\d{2,4})$/i);
  if (!match) {
    const error = new Error(`invalid extra viewport: ${text || '(empty)'}; expected [name:]WIDTHxHEIGHT`);
    error.code = 'INVALID_EXTRA_VIEWPORT';
    throw error;
  }
  const width = Number(match[2]);
  const height = Number(match[3]);
  if (width < 240 || width > 3840 || height < 200 || height > 2160) {
    const error = new Error(`extra viewport out of range: ${width}x${height}`);
    error.code = 'INVALID_EXTRA_VIEWPORT';
    throw error;
  }
  return {
    name: match[1] || `extra${index}_${width}x${height}`,
    width,
    height,
    mobile: width <= 680,
  };
}
