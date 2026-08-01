(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const providerDefaults = {
    gemini: {
      label: 'Google Gemini',
      primary: 'gemini-3.5-flash',
      fallback1: 'gemini-3.1-flash-lite',
      fallback2: 'gemini-flash-latest',
      help: 'Create or manage a Gemini API key',
      href: 'https://aistudio.google.com/app/apikey',
    },
    openai: {
      label: 'OpenAI',
      primary: 'gpt-5-mini',
      fallback1: 'gpt-5-nano',
      fallback2: 'gpt-4.1-mini',
      help: 'Create or manage an OpenAI API key',
      href: 'https://platform.openai.com/api-keys',
    },
    anthropic: {
      label: 'Anthropic',
      primary: 'claude-sonnet-4-5',
      fallback1: 'claude-haiku-4-5',
      fallback2: '',
      help: 'Create or manage an Anthropic API key',
      href: 'https://console.anthropic.com/settings/keys',
    },
    openrouter_auto: {
      label: 'OpenRouter Auto',
      primary: 'openrouter/auto',
      fallback1: '',
      fallback2: '',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    openrouter_free: {
      label: 'OpenRouter Free',
      primary: 'openrouter/free',
      fallback1: '',
      fallback2: '',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    ollama: {
      label: 'Ollama',
      primary: 'qwen3:8b',
      fallback1: 'llama3.1:8b',
      fallback2: '',
      help: 'Ollama runs models on your own server',
      href: 'https://ollama.com/library',
    },
    custom: {
      label: 'OpenAI-compatible endpoint',
      primary: '',
      fallback1: '',
      fallback2: '',
      help: 'Use any OpenAI-compatible chat-completions endpoint',
      href: 'https://platform.openai.com/docs/api-reference/chat',
    },
  };

  let activeProvider = '';
  let providerProfiles = {};
  let providerKeysSet = {};
  let modelRequestSequence = 0;

  function ensureModelControls() {
    const model = $('ai-model');
    const modelLabel = model?.closest('label');
    if (!model || !modelLabel) return;

    const firstNode = modelLabel.childNodes[0];
    if (firstNode?.nodeType === Node.TEXT_NODE) {
      firstNode.textContent = 'Model in use\n              ';
    }

    let options = $('ai-model-options');
    if (!options) {
      options = document.createElement('datalist');
      options.id = 'ai-model-options';
      model.insertAdjacentElement('afterend', options);
    }
    model.setAttribute('list', options.id);

    let hint = $('ai-model-hint');
    if (!hint) {
      hint = document.createElement('span');
      hint.id = 'ai-model-hint';
      hint.className = 'field-hint';
      hint.textContent = 'Checking models available to this API…';
      options.insertAdjacentElement('afterend', hint);
    }

    let fallback1 = $('ai-fallback-1');
    let fallback2 = $('ai-fallback-2');
    const fallbackRow = $('fallback-row');
    if (fallbackRow) {
      fallbackRow.classList.add('hidden');
      fallbackRow.hidden = true;
      fallbackRow.setAttribute('aria-hidden', 'true');
    }
    if (!fallback1) {
      fallback1 = document.createElement('input');
      fallback1.id = 'ai-fallback-1';
      fallback1.type = 'hidden';
      modelLabel.insertAdjacentElement('afterend', fallback1);
    }
    if (!fallback2) {
      fallback2 = document.createElement('input');
      fallback2.id = 'ai-fallback-2';
      fallback2.type = 'hidden';
      fallback1.insertAdjacentElement('afterend', fallback2);
    }

    let refresh = $('refresh-ai-models');
    if (!refresh) {
      const actions = document.createElement('div');
      actions.className = 'ai-model-actions';
      refresh = document.createElement('button');
      refresh.id = 'refresh-ai-models';
      refresh.type = 'button';
      refresh.className = 'secondary compact-button';
      refresh.textContent = 'Refresh available models';
      actions.append(refresh);
      const settingsFields = modelLabel.closest('.settings-fields');
      settingsFields?.append(actions);
    }
  }

  function ensureActivateButton() {
    let button = $('activate-ai');
    if (button) return button;
    button = document.createElement('button');
    button.id = 'activate-ai';
    button.type = 'button';
    button.className = 'secondary hidden';
    button.textContent = 'Use this AI';
    $('save-ai').insertAdjacentElement('afterend', button);
    button.addEventListener('click', activateSelectedProvider);
    return button;
  }

  function ensureDisconnectButton() {
    let button = $('disconnect-ai');
    if (button) return button;
    button = document.createElement('button');
    button.id = 'disconnect-ai';
    button.type = 'button';
    button.className = 'secondary hidden';
    button.textContent = 'Disconnect';
    ensureActivateButton().insertAdjacentElement('afterend', button);
    button.addEventListener('click', disconnectSelectedProvider);
    return button;
  }

  function profileFor(provider) {
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const saved = providerProfiles[provider] || {};
    return {
      model: saved.model || defaults.primary,
      fallback_1: saved.fallback_1 || '',
      fallback_2: saved.fallback_2 || '',
      base_url: saved.base_url || '',
      configured: Boolean(saved.configured),
      active: provider === activeProvider,
    };
  }

  function rememberProfiles(data) {
    activeProvider = data.active_provider || '';
    providerProfiles = data.profiles || {};
    providerKeysSet = Object.fromEntries(
      Object.entries(providerProfiles).map(([provider, profile]) => [
        provider,
        Boolean(profile.api_key_set),
      ]),
    );
  }

  function refreshProviderLabels() {
    Array.from($('ai-provider').options).forEach((option) => {
      const defaults = providerDefaults[option.value] || providerDefaults.custom;
      const profile = profileFor(option.value);
      const marker = profile.active ? '✓ ' : profile.configured ? '● ' : '';
      option.textContent = `${marker}${defaults.label}`;
    });
  }

  function applyProviderValues(provider) {
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const profile = profileFor(provider);
    $('ai-model').value = profile.model || defaults.primary;
    $('ai-fallback-1').value = profile.fallback_1 || '';
    $('ai-fallback-2').value = profile.fallback_2 || '';
    $('ai-base-url').value = profile.base_url || '';
    $('ai-key').value = '';
    $('ai-model-options').replaceChildren();
    $('ai-model-hint').textContent = 'Checking models available to this API…';
  }

  function setProviderFields() {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const local = provider === 'ollama';
    const custom = provider === 'custom';
    const openRouter = provider === 'openrouter_auto' || provider === 'openrouter_free';
    const keyStored = Boolean(providerKeysSet[provider]);

    $('api-key-field').classList.toggle('hidden', local);
    $('base-url-field').classList.toggle('hidden', !(local || custom));
    $('ai-model').readOnly = openRouter;
    $('ai-model').setAttribute('aria-readonly', String(openRouter));
    $('refresh-ai-models').disabled = false;
    $('provider-help-link').textContent = defaults.help;
    $('provider-help-link').href = defaults.href;

    if (local) {
      $('ai-base-url').placeholder = 'http://host:11434';
      $('api-key-hint').textContent = 'Ollama does not require an API key.';
    } else if (custom) {
      $('ai-base-url').placeholder = 'https://example.com/v1';
      $('api-key-hint').textContent = keyStored
        ? 'A key is already saved for this endpoint. Leave blank to keep it.'
        : 'Optional when the custom endpoint does not require authentication.';
    } else if (openRouter) {
      $('api-key-hint').textContent = keyStored
        ? 'OpenRouter key saved. Auto and Free are both available.'
        : 'One OpenRouter API key configures both Auto and Free modes.';
    } else {
      $('api-key-hint').textContent = keyStored
        ? 'API key already saved. Leave blank to keep it.'
        : 'Enter an API key for this provider.';
    }
  }

  function renderActiveProviderStatus() {
    const element = $('ai-active-status');
    if (!element) return;

    if (!activeProvider) {
      element.textContent = 'Active AI provider: none configured.';
      element.classList.remove('ok');
      return;
    }

    const defaults = providerDefaults[activeProvider] || providerDefaults.custom;
    const profile = profileFor(activeProvider);
    element.textContent = `Active AI provider: ${defaults.label}${profile.model ? ` · ${profile.model}` : ''}`;
    element.classList.toggle('ok', profile.configured);
  }

  function renderSelectedProviderStatus() {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const profile = profileFor(provider);
    const activate = ensureActivateButton();
    const disconnect = ensureDisconnectButton();

    renderActiveProviderStatus();

    activate.classList.toggle('hidden', !profile.configured || profile.active);
    activate.disabled = !profile.configured || profile.active;
    disconnect.classList.toggle('hidden', !profile.configured);
    disconnect.disabled = !profile.configured;

    if (profile.active) {
      $('ai-status').textContent = `Selected provider: ${defaults.label} is configured and currently in use.`;
      $('ai-status').classList.add('ok');
    } else if (profile.configured) {
      $('ai-status').textContent = `Selected provider: ${defaults.label} is configured and ready to activate.`;
      $('ai-status').classList.add('ok');
    } else {
      $('ai-status').textContent = `Selected provider: ${defaults.label} is not configured. Save its settings to make it available.`;
      $('ai-status').classList.remove('ok');
    }
  }

  function availableModelValues() {
    return Array.from($('ai-model-options').options)
      .map((option) => option.value.trim())
      .filter(Boolean);
  }

  function bestAvailableMatch(models, preferred) {
    if (!preferred) return '';
    if (models.includes(preferred)) return preferred;
    const versioned = models
      .filter((model) => model.startsWith(`${preferred}-`))
      .sort()
      .reverse();
    return versioned[0] || '';
  }

  function reconcileHiddenFallbacks(provider, models) {
    const primary = $('ai-model').value.trim();
    if (provider === 'openrouter_auto' || provider === 'openrouter_free') {
      $('ai-fallback-1').value = '';
      $('ai-fallback-2').value = '';
      return;
    }

    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const profile = profileFor(provider);
    const preferred = [
      profile.fallback_1,
      profile.fallback_2,
      defaults.fallback1,
      defaults.fallback2,
    ];
    const chosen = [];

    preferred.forEach((candidate) => {
      const match = bestAvailableMatch(models, candidate);
      if (match && match !== primary && !chosen.includes(match)) chosen.push(match);
    });

    if (provider === 'ollama' || provider === 'custom') {
      models.forEach((model) => {
        if (model !== primary && !chosen.includes(model) && chosen.length < 2) {
          chosen.push(model);
        }
      });
    }

    $('ai-fallback-1').value = chosen[0] || '';
    $('ai-fallback-2').value = chosen[1] || '';
  }

  function renderAvailableModels(data) {
    const models = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
    const options = $('ai-model-options');
    const current = $('ai-model').value.trim();
    options.replaceChildren();

    models.forEach((model) => {
      const option = document.createElement('option');
      option.value = model;
      options.append(option);
    });

    if (data.fixed && models[0]) {
      $('ai-model').value = models[0];
      $('ai-model').readOnly = true;
      $('ai-model-hint').textContent = 'This OpenRouter mode uses a fixed automatic router.';
    } else if (current && !models.includes(current)) {
      $('ai-model-hint').textContent = `${models.length} models reported by this API. The saved model is not currently listed.`;
    } else {
      $('ai-model-hint').textContent = `${models.length} compatible models reported by this API.`;
    }

    reconcileHiddenFallbacks($('ai-provider').value, models);
  }

  async function loadAvailableModels(provider = $('ai-provider').value) {
    const requestSequence = ++modelRequestSequence;
    const refreshButton = $('refresh-ai-models');
    refreshButton.disabled = true;
    refreshButton.textContent = 'Checking…';
    $('ai-model-hint').textContent = 'Checking models available to this API…';

    try {
      const data = await readJson(await fetch('/api/ai/models', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          provider,
          api_key: $('ai-key').value.trim(),
          base_url: $('ai-base-url').value.trim(),
        }),
      }));
      if (requestSequence !== modelRequestSequence || provider !== $('ai-provider').value) return;
      renderAvailableModels(data);
    } catch (error) {
      if (requestSequence !== modelRequestSequence || provider !== $('ai-provider').value) return;
      $('ai-model-options').replaceChildren();
      $('ai-model-hint').textContent = error.message || String(error);
    } finally {
      if (requestSequence === modelRequestSequence) {
        refreshButton.disabled = false;
        refreshButton.textContent = 'Refresh available models';
      }
    }
  }

  function validateSelectedModel() {
    const provider = $('ai-provider').value;
    if (provider === 'custom') return;
    const models = availableModelValues();
    const selected = $('ai-model').value.trim();
    if (models.length && !models.includes(selected)) {
      throw new Error('Select a model reported as available by this API.');
    }
  }

  async function fetchProfiles() {
    const data = await readJson(await fetch('/api/ai/profiles', {cache: 'no-store'}));
    rememberProfiles(data);
    return data;
  }

  async function loadSettings() {
    $('ai-active-status').textContent = 'Checking active AI provider…';
    $('ai-active-status').classList.remove('ok');
    $('ai-status').textContent = 'Checking selected provider…';
    ensureActivateButton();
    ensureDisconnectButton();
    try {
      const data = await fetchProfiles();
      const selected = data.active_provider || $('ai-provider').value || 'gemini';
      $('ai-provider').value = selected;
      applyProviderValues(selected);
      setProviderFields();
      refreshProviderLabels();
      renderSelectedProviderStatus();
      await loadAvailableModels(selected);
    } catch (error) {
      const text = error.message || String(error);
      $('ai-active-status').textContent = `Active AI provider could not be checked: ${text}`;
      $('ai-active-status').classList.remove('ok');
      $('ai-status').textContent = text;
      $('ai-status').classList.remove('ok');
    }
  }

  async function saveSettings() {
    const button = $('save-ai');
    const provider = $('ai-provider').value;
    button.disabled = true;
    button.textContent = 'Saving…';
    $('ai-status').textContent = 'Saving selected provider settings…';

    try {
      await loadAvailableModels(provider);
      validateSelectedModel();
      await readJson(await fetch('/api/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          provider,
          api_key: $('ai-key').value.trim(),
          model: $('ai-model').value.trim(),
          fallback_1: $('ai-fallback-1').value.trim(),
          fallback_2: $('ai-fallback-2').value.trim(),
          base_url: $('ai-base-url').value.trim(),
        }),
      }));

      await fetchProfiles();
      $('ai-provider').value = provider;
      applyProviderValues(provider);
      setProviderFields();
      refreshProviderLabels();
      renderSelectedProviderStatus();
      await loadAvailableModels(provider);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    } finally {
      button.disabled = false;
      button.textContent = 'Save AI settings';
    }
  }

  async function activateSelectedProvider() {
    const button = ensureActivateButton();
    const provider = $('ai-provider').value;
    button.disabled = true;
    button.textContent = 'Switching…';
    $('ai-status').textContent = 'Switching active AI provider…';

    try {
      const data = await readJson(await fetch('/api/ai/activate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({provider}),
      }));
      rememberProfiles(data);
      $('ai-provider').value = provider;
      applyProviderValues(provider);
      setProviderFields();
      refreshProviderLabels();
      renderSelectedProviderStatus();
      await loadAvailableModels(provider);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    } finally {
      button.textContent = 'Use this AI';
      renderSelectedProviderStatus();
    }
  }

  async function disconnectSelectedProvider() {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const wasActive = profileFor(provider).active;
    const linkedOpenRouter = provider === 'openrouter_auto' || provider === 'openrouter_free';
    const scope = linkedOpenRouter
      ? 'OpenRouter Auto and OpenRouter Free'
      : defaults.label;

    if (!window.confirm(`Disconnect ${scope}? Saved credentials and model settings will be removed.`)) {
      return;
    }

    const button = ensureDisconnectButton();
    button.disabled = true;
    button.textContent = 'Disconnecting…';
    $('ai-status').textContent = `Disconnecting ${scope}…`;

    try {
      const data = await readJson(await fetch(
        `/api/ai/providers/${encodeURIComponent(provider)}`,
        {method: 'DELETE'},
      ));
      rememberProfiles(data);
      const selected = wasActive && data.active_provider
        ? data.active_provider
        : provider;
      $('ai-provider').value = selected;
      applyProviderValues(selected);
      setProviderFields();
      refreshProviderLabels();
      renderSelectedProviderStatus();
      await loadAvailableModels(selected);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    } finally {
      button.textContent = 'Disconnect';
      renderSelectedProviderStatus();
    }
  }

  ensureModelControls();
  $('ai-provider').addEventListener('change', () => {
    const provider = $('ai-provider').value;
    applyProviderValues(provider);
    setProviderFields();
    renderSelectedProviderStatus();
    void loadAvailableModels(provider);
  });
  $('ai-model').addEventListener('change', () => {
    reconcileHiddenFallbacks($('ai-provider').value, availableModelValues());
  });
  $('refresh-ai-models').addEventListener('click', () => void loadAvailableModels());
  $('save-ai').addEventListener('click', saveSettings);
  window.addEventListener('playlistmuse-ai-settings-opened', loadSettings);
})();
