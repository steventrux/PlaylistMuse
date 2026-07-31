(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const providerDefaults = {
    gemini: {
      label: 'Google Gemini',
      primary: 'gemini-3.6-flash',
      fallback1: 'gemini-3.5-flash',
      fallback2: 'gemini-3.5-flash-lite',
      help: 'Create or manage a Gemini API key',
      href: 'https://aistudio.google.com/app/apikey',
    },
    openai: {
      label: 'OpenAI',
      primary: 'gpt-5-mini',
      fallback1: 'gpt-4.1-mini',
      fallback2: 'gpt-4.1-nano',
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

  function modelChain(profile) {
    return [profile.model, profile.fallback_1, profile.fallback_2]
      .filter(Boolean)
      .join(' → ');
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
      const marker = profile.active ? '● ' : profile.configured ? '✓ ' : '';
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
    $('fallback-row').classList.toggle('hidden', openRouter);
    $('ai-model').readOnly = openRouter;
    $('ai-model').setAttribute('aria-readonly', String(openRouter));
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
        ? 'OpenRouter key saved. The same key is shared by Auto and Free.'
        : 'One OpenRouter API key is shared by the Auto and Free modes.';
    } else {
      $('api-key-hint').textContent = keyStored
        ? 'API key already saved. Leave blank to keep it.'
        : 'Enter an API key for this provider.';
    }
  }

  function renderSelectedProviderStatus() {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const profile = profileFor(provider);
    const activate = ensureActivateButton();

    activate.classList.toggle('hidden', !profile.configured || profile.active);
    activate.disabled = !profile.configured || profile.active;

    if (profile.active) {
      $('ai-status').textContent = `Active: ${defaults.label} · ${modelChain(profile)}`;
      $('ai-status').classList.add('ok');
    } else if (profile.configured) {
      $('ai-status').textContent = `Configured: ${defaults.label} · select “Use this AI” to activate it.`;
      $('ai-status').classList.add('ok');
    } else {
      $('ai-status').textContent = `Configure ${defaults.label} to make it available.`;
      $('ai-status').classList.remove('ok');
    }
  }

  async function fetchProfiles() {
    const data = await readJson(await fetch('/api/ai/profiles', {cache: 'no-store'}));
    rememberProfiles(data);
    return data;
  }

  async function loadSettings() {
    $('ai-status').textContent = 'Checking AI configuration…';
    ensureActivateButton();
    try {
      const data = await fetchProfiles();
      const selected = data.active_provider || $('ai-provider').value || 'gemini';
      $('ai-provider').value = selected;
      applyProviderValues(selected);
      setProviderFields();
      refreshProviderLabels();
      renderSelectedProviderStatus();
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    }
  }

  async function saveSettings() {
    const button = $('save-ai');
    const provider = $('ai-provider').value;
    button.disabled = true;
    button.textContent = 'Saving…';
    $('ai-status').textContent = 'Saving AI settings…';

    try {
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
      refreshProviderLabels();
      renderSelectedProviderStatus();
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    } finally {
      button.textContent = 'Use this AI';
      button.disabled = false;
      renderSelectedProviderStatus();
    }
  }

  $('ai-provider').addEventListener('change', () => {
    applyProviderValues($('ai-provider').value);
    setProviderFields();
    renderSelectedProviderStatus();
  });
  $('save-ai').addEventListener('click', saveSettings);
  window.addEventListener('playlistmuse-ai-settings-opened', loadSettings);
})();