(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  // Model choices always come from live provider discovery (see loadAvailableModels /
  // renderAvailableModels) -- this table only carries per-provider labels and help links.
  const providerDefaults = {
    gemini: {
      label: 'Google Gemini',
      help: 'Create or manage a Gemini API key',
      href: 'https://aistudio.google.com/app/apikey',
    },
    openai: {
      label: 'OpenAI',
      help: 'Create or manage an OpenAI API key',
      href: 'https://platform.openai.com/api-keys',
    },
    anthropic: {
      label: 'Anthropic',
      help: 'Create or manage an Anthropic API key',
      href: 'https://console.anthropic.com/settings/keys',
    },
    openrouter_auto: {
      label: 'OpenRouter Auto',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    openrouter_free: {
      label: 'OpenRouter Free',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    ollama: {
      label: 'Ollama',
      help: 'Ollama runs models on your own server',
      href: 'https://ollama.com/library',
    },
    custom: {
      label: 'OpenAI-compatible endpoint',
      help: 'Use any OpenAI-compatible chat-completions endpoint',
      href: 'https://platform.openai.com/docs/api-reference/chat',
    },
  };

  let activeProvider = '';
  let providerProfiles = {};
  let providerKeysSet = {};
  let modelRequestSequence = 0;

  // Fallbacks cascade automatically (no manual editing, see reconcileHiddenFallbacks) --
  // 8 slots comfortably cover every stable model a provider like Gemini currently reports.
  const MAX_FALLBACKS = 8;
  const fallbackFieldId = (index) => `ai-fallback-${index}`;

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

    // Browsers filter datalist suggestions against the text already in the field, so a
    // pre-filled value hides every option except the exact match. Clearing the value on
    // focus lets the popup show the complete list; restore it on blur if nothing was chosen.
    let valueBeforeFocus = '';
    model.addEventListener('focus', () => {
      if (model.readOnly) return;
      valueBeforeFocus = model.value;
      model.value = '';
    });
    model.addEventListener('blur', () => {
      if (!model.value.trim()) {
        model.value = valueBeforeFocus;
      }
    });

    let hint = $('ai-model-hint');
    if (!hint) {
      hint = document.createElement('span');
      hint.id = 'ai-model-hint';
      hint.className = 'field-hint';
      hint.textContent = 'Checking models available to this API…';
      options.insertAdjacentElement('afterend', hint);
    }

    const fallbackRow = $('fallback-row');
    if (fallbackRow) {
      fallbackRow.classList.add('hidden');
      fallbackRow.hidden = true;
      fallbackRow.setAttribute('aria-hidden', 'true');
    }
    let previousFallback = modelLabel;
    for (let index = 1; index <= MAX_FALLBACKS; index += 1) {
      const id = fallbackFieldId(index);
      let fallback = $(id);
      if (!fallback) {
        fallback = document.createElement('input');
        fallback.id = id;
        fallback.type = 'hidden';
        previousFallback.insertAdjacentElement('afterend', fallback);
      }
      previousFallback = fallback;
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
    const saved = providerProfiles[provider] || {};
    const profile = {
      model: saved.model || '',
      base_url: saved.base_url || '',
      configured: Boolean(saved.configured),
      active: provider === activeProvider,
    };
    for (let index = 1; index <= MAX_FALLBACKS; index += 1) {
      const key = `fallback_${index}`;
      profile[key] = saved[key] || '';
    }
    return profile;
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
    const profile = profileFor(provider);
    $('ai-model').value = profile.model || '';
    for (let index = 1; index <= MAX_FALLBACKS; index += 1) {
      $(fallbackFieldId(index)).value = profile[`fallback_${index}`] || '';
    }
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

  function reconcileHiddenFallbacks(provider, models, fallbackOrder = []) {
    const primary = $('ai-model').value.trim();
    const setFallbacks = (values) => {
      for (let index = 1; index <= MAX_FALLBACKS; index += 1) {
        $(fallbackFieldId(index)).value = values[index - 1] || '';
      }
    };

    if (provider === 'openrouter_auto' || provider === 'openrouter_free') {
      setFallbacks([]);
      return;
    }

    // The chain always cascades through fallbackOrder (the provider's own verified
    // recency order, already filtered to stable models) -- no manual editing, no stale
    // carried-over values from a previous save.
    const chosen = [];
    fallbackOrder.forEach((candidate) => {
      const match = bestAvailableMatch(models, candidate);
      if (match && match !== primary && !chosen.includes(match)) chosen.push(match);
    });

    if (provider === 'ollama' || provider === 'custom') {
      // No verified recency signal for these -- cascade through whatever else is available.
      models.forEach((model) => {
        if (model !== primary && !chosen.includes(model) && chosen.length < MAX_FALLBACKS) {
          chosen.push(model);
        }
      });
    }

    setFallbacks(chosen.slice(0, MAX_FALLBACKS));
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

    const recommended =
      typeof data.recommended_model === 'string' ? data.recommended_model.trim() : '';
    const fallbackOrder = Array.isArray(data.fallback_order)
      ? data.fallback_order.filter(Boolean)
      : [];

    if (data.fixed && models[0]) {
      $('ai-model').value = models[0];
      $('ai-model').readOnly = true;
      $('ai-model-hint').textContent = 'This OpenRouter mode uses a fixed automatic router.';
    } else if (!current && recommended) {
      // Only a verified recency signal (a provider's own alias or a real creation date)
      // ever pre-selects a model -- never a guess based on a model's name.
      $('ai-model').value = recommended;
      $('ai-model-hint').textContent =
        `${models.length} compatible models reported by this API. ` +
        `Pre-selected the most recent: ${recommended}.`;
    } else if (!current) {
      $('ai-model-hint').textContent = models.length
        ? `${models.length} compatible models reported by this API. Select one to continue.`
        : 'No compatible models reported by this API. Select one to continue.';
    } else if (current && !models.includes(current)) {
      $('ai-model-hint').textContent = `${models.length} models reported by this API. The saved model is not currently listed.`;
    } else {
      $('ai-model-hint').textContent = `${models.length} compatible models reported by this API.`;
    }

    reconcileHiddenFallbacks($('ai-provider').value, models, fallbackOrder);
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
    const selected = $('ai-model').value.trim();
    if (!selected) {
      throw new Error('Select a model to continue.');
    }
    if (provider === 'custom') return;
    const models = availableModelValues();
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
      const fallbackFields = {};
      for (let index = 1; index <= MAX_FALLBACKS; index += 1) {
        fallbackFields[`fallback_${index}`] = $(fallbackFieldId(index)).value.trim();
      }
      await readJson(await fetch('/api/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          provider,
          api_key: $('ai-key').value.trim(),
          model: $('ai-model').value.trim(),
          ...fallbackFields,
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
