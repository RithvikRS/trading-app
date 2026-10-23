import { useEffect, useRef, useState } from 'react'
import { Check, LoaderCircle, Settings2 } from 'lucide-react'
import type { AuthController, Screen } from './auth'
import type { DisplayPreferences } from './preferences'

export default function DisplaySettings({ auth, screen, busy }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean }) {
  const { preferences: saved, preferenceStatus: status } = screen
  const [draft, setDraft] = useState<DisplayPreferences>(saved)
  const [reloading, setReloading] = useState(false)
  const notice = useRef<HTMLParagraphElement>(null)
  useEffect(() => { setDraft(saved); setReloading(false) }, [saved])
  useEffect(() => { if (status === 'conflict') notice.current?.focus() }, [status])
  const dirty = draft.theme !== saved.theme || draft.display_currency !== saved.display_currency || draft.amount_masked !== saved.amount_masked
  const conflict = status === 'conflict'
  return <section className="ws-card ws-display" aria-labelledby="display-heading" id="display-settings">
    <div className="ws-display-heading"><div className="ws-card-title"><Settings2 size={21} aria-hidden="true" /><h2 id="display-heading">Display preferences</h2></div><span className="ws-pill">Your account</span></div>
    <p>Make this space your own. Saved settings follow your account across devices.</p>
    {conflict && <p className="ws-notice" role="alert" tabIndex={-1} ref={notice}>These settings changed elsewhere. Your changes weren’t saved. Reload saved settings to discard this draft and review the latest choices.</p>}
    <form onSubmit={event => { event.preventDefault(); void auth.savePreferences({ theme: draft.theme, display_currency: draft.display_currency, amount_masked: draft.amount_masked }) }}>
      <fieldset disabled={busy || conflict}>
        <legend className="sr-only">Workspace display</legend>
        <div className="ws-preference-fields"><div><label htmlFor="display-theme">Appearance</label><select id="display-theme" value={draft.theme} onChange={event => setDraft({ ...draft, theme: event.target.value as 'light' | 'dark' })}><option value="light">Light · Indigo & Apricot</option><option value="dark">Dark · Indigo & Apricot</option></select><p className="ws-hint">Applied after you save.</p></div>
          <div><label htmlFor="display-currency">Display currency</label><select id="display-currency" value={draft.display_currency} onChange={event => setDraft({ ...draft, display_currency: event.target.value as 'INR' | 'USD' })}><option value="INR">INR · Indian rupee</option><option value="USD">USD · US dollar</option></select><p className="ws-hint">For future reporting views. Source currencies stay unchanged.</p></div>
          <div><label htmlFor="display-masking">Amount privacy</label><select id="display-masking" value={draft.amount_masked ? 'hidden' : 'visible'} onChange={event => setDraft({ ...draft, amount_masked: event.target.value === 'hidden' })}><option value="hidden">Hide amounts by default</option><option value="visible">Show amounts after sign-in</option></select><p className="ws-hint">A display choice. Your session still controls access.</p></div>
        </div>
      </fieldset>
      <div className="ws-display-actions"><div>{conflict ? <button type="button" className="ws-secondary" disabled={busy} onClick={() => { setReloading(true); void auth.reloadPreferences() }}>{reloading ? 'Reloading…' : 'Reload saved settings'}</button> : <><button type="submit" className="ws-secondary" disabled={busy || (!dirty && saved.revision > 0)}>{status === 'saving' ? <><LoaderCircle className="ws-spin" size={16} aria-hidden="true" />Saving…</> : 'Save preferences'}</button>{dirty && <button type="button" className="ws-text" disabled={busy} onClick={() => setDraft(saved)}>Discard changes</button>}</>}</div>
        <p className="ws-save-status" role="status">{dirty ? 'Unsaved changes' : status === 'saved' ? <><Check size={15} aria-hidden="true" />Saved to your account</> : saved.revision === 0 ? 'Defaults · not saved yet' : 'Saved account settings'}</p></div>
      <p className="ws-hint">Unsaved changes are cleared when the workspace locks or you leave the tab.</p>
    </form>
  </section>
}
