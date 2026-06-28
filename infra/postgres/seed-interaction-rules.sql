-- Curated drug-interaction rule set (Codebase PRD §7.3 / §5.4).
-- ILLUSTRATIVE ONLY — a small open rule set over RxNorm codes, explicitly NOT a
-- substitute for a licensed clinical drug-interaction database (Lexicomp, First Databank).
-- Pairs are unordered; check_pairs() queries symmetrically. RxNorm codes chosen to match
-- the Synthea-generated medications so the demo surfaces real interactions.
-- Idempotent: truncate then insert (the loader never touches this reference table).

TRUNCATE interaction_rules RESTART IDENTITY;

INSERT INTO interaction_rules (rxnorm_code_a, rxnorm_code_b, severity, description) VALUES
  -- lisinopril (ACE inhibitor) + naproxen (NSAID): demo-patient-1 has BOTH
  ('314076', '849574', 'moderate',
   'NSAID (naproxen) may reduce the antihypertensive effect of the ACE inhibitor (lisinopril) and increase the risk of acute renal impairment, especially with diuretics.'),
  -- simvastatin + amlodipine: amlodipine raises simvastatin exposure
  ('314231', '308136', 'moderate',
   'Amlodipine increases simvastatin plasma levels; limit simvastatin to 20 mg/day to reduce myopathy/rhabdomyolysis risk.'),
  -- naproxen (NSAID) + hydrochlorothiazide (thiazide): blunted diuresis + renal risk
  ('849574', '310798', 'moderate',
   'NSAIDs can blunt the diuretic/antihypertensive effect of thiazides and increase renal risk; monitor blood pressure and renal function.'),
  -- oxycodone/APAP (Percocet) + hydrocodone/APAP: duplicate opioid + acetaminophen
  ('1049625', '856987', 'major',
   'Concurrent opioid combinations (oxycodone + hydrocodone) cause additive CNS/respiratory depression, plus cumulative acetaminophen toward hepatotoxic doses.'),
  -- oxycodone/APAP + fentanyl: two opioids
  ('1049625', '245134', 'major',
   'Two concurrent opioids (oxycodone + transdermal fentanyl): additive respiratory depression and overdose risk.'),
  -- lisinopril + hydrochlorothiazide: common combo, monitor (low severity for variety)
  ('314076', '310798', 'minor',
   'Commonly co-prescribed (ACE inhibitor + thiazide); monitor serum potassium and renal function — generally beneficial, not contraindicated.');
