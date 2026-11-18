// Read only the selected collection; content generation and settlement are separate.
export function assetInfoSelectionMetrics() {
  const config = document.querySelector('[data-qb-asset-info-config]');
  if (!config) return {present:false, problems:[]};
  const root = document.querySelector('[data-qb-asset-info-panel]');
  const assets = root ? [...root.querySelectorAll('.qb-info-code')].map(e => e.textContent.trim()) : [];
  const state = window.QBAssetInfoPanel?.getSelectionState?.();
  const problems = [];
  try {
    const binding = JSON.parse(config.textContent);
    const targets = document.querySelectorAll(binding.target_selector);
    const panels = document.querySelectorAll('[data-qb-asset-info-panel]');
    if (document.querySelectorAll('[data-qb-asset-info-config]').length !== 1 || targets.length > 1 || panels.length > 1)
      problems.push('ASSET_INFO_SELECTION_DUPLICATE');
    if (targets.length !== 1 || panels.length !== 1 || targets[0] !== root)
      problems.push('ASSET_INFO_SELECTION_UNBOUND');
  } catch (_) { problems.push('ASSET_INFO_SELECTION_UNBOUND'); }
  if (!root || !window.QBAssetInfoPanel) problems.push('ASSET_INFO_SELECTION_UNBOUND');
  else if (state) {
    if (!['ready', 'empty'].includes(state.status)) problems.push('ASSET_INFO_SELECTION_' + String(state.status).toUpperCase());
    else if (state.status === 'empty' ? state.total !== 0 || assets.length !== 0
      : !(state.total > 0) || !state.visible_assets?.length || state.visible_assets.length > 50
        || JSON.stringify(state.visible_assets) !== JSON.stringify(assets)) problems.push('ASSET_INFO_SELECTION_MISMATCH');
  } else if (!assets.length) problems.push('ASSET_INFO_SELECTION_UNBOUND');
  // Do not expose credentials or wait for content/cache/identity to become available.
  return {present:true, status:state?.status || 'legacy', total:state?.total ?? null,
    visible_assets:assets, problems};
}
