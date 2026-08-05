(() => {
  'use strict';

  const DIMENSIONS = [
    {key: 'genre', points: 3, pattern: /\b(rock|blues|jazz|pop|soul|funk|metal|punk|folk|country|rap|hip[- ]?hop|electronic|dance|classical|reggae|indie|alternative|grunge|disco|r&b|genere|sottogenere)\b/i},
    {key: 'period', points: 3, pattern: /\b(19\d{2}|20\d{2}|anni\s*['’]?\d{2}|(?:sixties|seventies|eighties|nineties)|(?:from|between|dal|tra)\s+\d{4})\b/i},
    {key: 'mood', points: 3, pattern: /\b(mood|atmosfer[ae]|energia|energ(?:y|etic)|rilassante|calm|chill|romantic|dark|melanchol|happy|triste|epic|intense|soft|warm)\w*\b/i},
    {key: 'context', points: 2, pattern: /\b(viaggio|road[ -]?trip|drive|driving|workout|allenamento|studio|study|party|festa|cena|dinner|sleep|relax|running|corsa|lavoro|work)\b/i},
    {key: 'references', points: 2, pattern: /\b(?:come|simile a|nello stile di|inspired by|like|similar to|style of)\b/i},
    {key: 'language', points: 2, pattern: /\b(italian[oaie]?|ingles[ei]|english|french|frances[ei]|spanish|spagnol[oaie]?|lingua|language|from (?:italy|uk|usa)|provenienz[ae])\b/i},
    {key: 'popularity', points: 3, pattern: /\b(famos[oaie]|not[oaie]|popolar[ei]|mainstream|hit|hidden gems?|deep cuts?|poco conosciut[oaie]|underground|discovery|scoperte?)\b/i},
    {key: 'sound', points: 3, pattern: /\b(chitarr[ae]|guitars?|piano|synth|batteria|drums?|acoustic|acustic[oa]|instrumental|voce|vocals?|bass[oa]?|orchestral|lo[- ]?fi)\b/i},
  ];

  const STRUCTURES = [
    {key: 'ordering', points: 4, pattern: /\b(ordina|ordinat[oaie]|in ordine|sort(?:ed)?|chronological|cronologic[oa]|prima|poi|infine)\b/i},
    {key: 'alternation', points: 7, pattern: /\b(alterna|alternando|alternat(?:e|ing)|a turno)\b/i},
    {key: 'progression', points: 8, pattern: /\b(crescent[ei]|decrescent[ei]|gradualmente|progressiv\w*|builds? up|rising energy|energia crescente|parte .* (?:e|per poi) .*|start .* end)\b/i},
    {key: 'proportions', points: 6, pattern: /(?:\b\d{1,3}\s*%\b|\bmetà\b|\bhalf\b|\bun terzo\b|\bone third\b|\bquota\b|\bproporzion[ei]\b)/i},
    {key: 'transitions', points: 6, pattern: /\b(transizion[ei]|passaggi? fluid[io]|smooth transitions?|coherent flow|flusso coerente)\b/i},
    {key: 'sections', points: 7, pattern: /\b(sezion[ei]|fas[ei]|capitol[io]|divid[ei]|suddivid[ei]|in \d+ parti|sections?|phases?)\b/i},
  ];

  const SOFT_CONSTRAINT = /\b(preferibilmente|possibilmente|circa|più o meno|non tropp[oaie]|prefer(?:ably)?|roughly|about|ideally|try to)\b/gi;
  const RELATION = /\b(?:degli?|delle?|dal|tra|dopo|between|from|after)\b|\b(?:mentre|ma|senza|while|but|without|all'inizio|alla fine|at the (?:start|end))\b/gi;
  const AMBIGUOUS = /\b(bell[oaie]|brutt[oaie]|particolar[ei]|interessante|originale|giust[oa]|nice|good|bad|interesting|special|original|the right)\b/gi;
  const IMPRECISE = /\b(non tropp[oaie]|abbastanza|un po['’]?|circa|più o meno|not too|quite|somewhat|roughly|about)\b/gi;
  const ONLY_CONSTRAINT = /\b(?:solo|soltanto|only)\b/gi;
  const INCLUDE_CONSTRAINT = /\b(?:includ[ei]|inserisci|include|add)\b/gi;
  const EXCLUDE_CONSTRAINT = /\b(?:senza|esclud[ei]|evita|non includere|exclude|without|avoid|no)\b/gi;

  const EXTERNAL_FILTERS = [
    {setting: 'excludeLive', target: /\b(?:live|dal vivo)\b/i},
    {setting: 'excludeCovers', target: /\bcover\b/i},
    {setting: 'excludeRemixes', target: /\bremix(?:es)?\b/i},
  ];

  function uniqueMatches(text, pattern) {
    return new Set(text.match(pattern) || []).size;
  }

  function countHardConstraints(prompt, settings) {
    let promptConstraints = uniqueMatches(prompt, ONLY_CONSTRAINT)
      + uniqueMatches(prompt, INCLUDE_CONSTRAINT)
      + uniqueMatches(prompt, EXCLUDE_CONSTRAINT);

    const externalConstraints = EXTERNAL_FILTERS.filter(({setting, target}) => (
      settings[setting] && !target.test(prompt)
    )).length;

    return promptConstraints + externalConstraints;
  }

  function detectClarityIssues(prompt) {
    const issues = [];
    const femaleOnly = /\b(?:solo|soltanto|only)\s+(?:(?:con|da|di)\s+)?(?:cantanti|artist[ei]|voci|singers?|artists?|vocals?)\s+(?:donn[ae]|femminil[ei]|female|women)\b/i.test(prompt);
    const includesElvis = /\b(?:includ[ei]|inserisci|include|add)\s+(?:anche\s+)?(?:elvis|elwis)(?:\s+presley)?\b/i.test(prompt);
    const misspelledElvis = /\belwis(?:\s+presley)?\b/i.test(prompt);

    if (femaleOnly && includesElvis) issues.push('conflicting artist constraints');
    if (uniqueMatches(prompt, AMBIGUOUS)) issues.push('subjective terms');
    if (misspelledElvis) issues.push('possible artist typo');
    return issues;
  }

  function quantityPoints(trackCount) {
    if (trackCount <= 15) return 0;
    if (trackCount <= 30) return 3;
    if (trackCount <= 50) return 7;
    if (trackCount <= 100) return 11;
    return 15;
  }

  function level(score) {
    if (score < 20) return 'Simple';
    if (score < 40) return 'Detailed';
    if (score < 65) return 'Complex';
    if (score < 85) return 'Very complex';
    return 'Extreme';
  }

  function clarityLevel(score) {
    if (score >= 90) return 'Excellent';
    if (score >= 75) return 'Good';
    if (score >= 55) return 'Fair';
    return 'Needs clarification';
  }

  function analyze(text, settings = {}) {
    const prompt = String(text || '').trim();
    if (!prompt) return null;

    const dimensions = DIMENSIONS.filter(({pattern}) => pattern.test(prompt));
    const dimensionScore = Math.min(20, dimensions.reduce((sum, item) => sum + item.points, 0));
    const hardConstraints = countHardConstraints(prompt, settings);
    const softConstraints = uniqueMatches(prompt, SOFT_CONSTRAINT);
    const constraintScore = Math.min(25, (4 * hardConstraints) + (2 * softConstraints));
    const structures = STRUCTURES.filter(({pattern}) => pattern.test(prompt));
    const structureScore = Math.min(25, structures.reduce((sum, item) => sum + item.points, 0));
    const relations = Math.min(5, uniqueMatches(prompt, RELATION));
    const relationScore = Math.min(15, 3 * relations);
    const tracks = Math.max(1, Number.parseInt(settings.trackCount, 10) || 25);
    const quantityScore = quantityPoints(tracks);
    const score = Math.min(100, 5 + dimensionScore + constraintScore + structureScore + relationScore + quantityScore);

    const ambiguityCount = uniqueMatches(prompt, AMBIGUOUS);
    const imprecisionCount = uniqueMatches(prompt, IMPRECISE);
    const clarityIssues = detectClarityIssues(prompt);
    const conflictCount = clarityIssues.includes('conflicting artist constraints') ? 1 : 0;
    const typoCount = clarityIssues.includes('possible artist typo') ? 1 : 0;
    const clarity = Math.max(0, 100 - (10 * ambiguityCount) - (25 * conflictCount)
      - (5 * imprecisionCount) - (5 * typoCount));

    return {
      score,
      level: level(score),
      clarity,
      clarityLevel: clarityLevel(clarity),
      clarityIssues,
      dimensions: dimensions.length,
      hardConstraints,
      softConstraints,
      structures: structures.length,
      relations,
    };
  }

  function init() {
    const prompt = document.getElementById('prompt');
    const indicator = document.getElementById('prompt-complexity');
    if (!prompt || !indicator) return;

    const score = document.getElementById('prompt-complexity-score');
    const summary = document.getElementById('prompt-complexity-summary');
    const clarity = document.getElementById('prompt-clarity');
    let timer = null;

    const render = () => {
      const result = analyze(prompt.value, {
        trackCount: document.getElementById('track-count')?.value,
        excludeLive: document.getElementById('exclude-live')?.checked,
        excludeCovers: document.getElementById('exclude-covers')?.checked,
        excludeRemixes: document.getElementById('exclude-remixes')?.checked,
      });
      indicator.classList.toggle('hidden', !result);
      if (!result) return;

      score.textContent = `${result.level} · ${result.score}/100`;
      const constraintCount = result.hardConstraints + result.softConstraints;
      summary.textContent = [
        `${result.dimensions} musical ${result.dimensions === 1 ? 'dimension' : 'dimensions'}`,
        `${constraintCount} ${constraintCount === 1 ? 'constraint' : 'constraints'}`,
        `${result.structures} structural ${result.structures === 1 ? 'rule' : 'rules'}`,
      ].join(' · ');
      const issueSummary = result.clarityIssues.length ? ` · ${result.clarityIssues.join(' · ')}` : '';
      clarity.textContent = `Clarity: ${result.clarityLevel}${issueSummary}`;
    };

    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(render, 500);
    };

    prompt.addEventListener('input', schedule);
    ['track-count', 'exclude-live', 'exclude-covers', 'exclude-remixes'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', schedule);
    });
  }

  window.PlaylistMusePromptComplexity = {analyze, quantityPoints};
  if (typeof document !== 'undefined') init();
})();
