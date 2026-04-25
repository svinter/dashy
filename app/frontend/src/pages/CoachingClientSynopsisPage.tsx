import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, openExternal } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SynopsisClient {
  id: number;
  name: string;
  obsidian_name: string | null;
  company_name: string;
  gdrive_coaching_docs_url: string | null;
  manifest_gdoc_url: string | null;
  coaching_agreement_url: string | null;
  shared_notes_url: string | null;
}

interface PastSession {
  date: string;
  day_label: string;
  session_number: number | null;
  obsidian_note_path: string | null;
  summary: string;
}

interface FutureSession {
  date: string;
  day_label: string;
  days_until: number;
  event_title: string;
}

interface SynopsisResponse {
  client: SynopsisClient;
  past_sessions: PastSession[];
  future_sessions: FutureSession[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function obsidianNoteUrl(notePath: string): string {
  return `obsidian://open?vault=MyNotes&file=${encodeURIComponent(notePath)}`;
}

function obsidianClientUrl(obsidianName: string): string {
  return `obsidian://open?vault=MyNotes&file=${encodeURIComponent(`1 People/${obsidianName}.md`)}`;
}

function daysUntilLabel(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  return `in ${days} days`;
}

// ---------------------------------------------------------------------------
// CoachingClientSynopsisPage
// ---------------------------------------------------------------------------

export function CoachingClientSynopsisPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['coaching-client-synopsis', id],
    queryFn: () => api.get<SynopsisResponse>(`/coaching/clients/${id}/synopsis`),
    staleTime: 0,
  });

  if (isLoading) {
    return (
      <div className="coaching-synopsis-page">
        <div className="coaching-synopsis-loading">Generating briefing…</div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="coaching-synopsis-page">
        <button className="coaching-synopsis-back" onClick={() => navigate('/coaching/clients')}>← back</button>
        <div className="coaching-synopsis-error">Could not load synopsis.</div>
      </div>
    );
  }

  const { client, past_sessions, future_sessions } = data;

  return (
    <div className="coaching-synopsis-page">
      {/* Back */}
      <button className="coaching-synopsis-back" onClick={() => navigate('/coaching/clients')}>← back</button>

      {/* Title */}
      <div className="coaching-synopsis-title-block">
        <h1 className="coaching-synopsis-name">{client.name}</h1>
        {client.company_name && (
          <div className="coaching-synopsis-company">{client.company_name}</div>
        )}
      </div>

      {/* Header links */}
      <div className="coaching-synopsis-links">
        {client.obsidian_name && (
          <button className="coaching-link-btn" onClick={() => openExternal(obsidianClientUrl(client.obsidian_name!))}>
            📓 obsidian
          </button>
        )}
        {client.gdrive_coaching_docs_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(client.gdrive_coaching_docs_url!)}>
            📁 coaching docs
          </button>
        )}
        {client.manifest_gdoc_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(client.manifest_gdoc_url!)}>
            📄 manifest
          </button>
        )}
        {client.coaching_agreement_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(client.coaching_agreement_url!)}>
            📋 agreement
          </button>
        )}
        {client.shared_notes_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(client.shared_notes_url!)}>
            🤝 shared notes
          </button>
        )}
      </div>

      {/* Future sessions */}
      <section className="coaching-synopsis-section">
        <h2 className="coaching-synopsis-section-title">Upcoming</h2>
        {future_sessions.length === 0 ? (
          <div className="coaching-synopsis-empty">No upcoming sessions scheduled</div>
        ) : (
          future_sessions.map((s, i) => (
            <div key={i} className="coaching-synopsis-future-card">
              <span className="coaching-synopsis-session-date">{s.day_label}</span>
              <span className="coaching-synopsis-days-until">{daysUntilLabel(s.days_until)}</span>
              {s.event_title && (
                <span className="coaching-synopsis-event-title">{s.event_title}</span>
              )}
            </div>
          ))
        )}
      </section>

      {/* Past sessions */}
      <section className="coaching-synopsis-section">
        <h2 className="coaching-synopsis-section-title">Recent sessions</h2>
        {past_sessions.length === 0 ? (
          <div className="coaching-synopsis-empty">No confirmed sessions</div>
        ) : (
          past_sessions.map((s, i) => (
            <div key={i} className="coaching-synopsis-past-card">
              <div className="coaching-synopsis-session-header">
                <span className="coaching-synopsis-session-date">{s.day_label}</span>
                {s.session_number != null && (
                  <span className="coaching-synopsis-session-num">#{s.session_number}</span>
                )}
                {s.obsidian_note_path && (
                  <button
                    className="coaching-link-btn"
                    onClick={() => openExternal(obsidianNoteUrl(s.obsidian_note_path!))}
                    title="Open in Obsidian"
                  >→ note</button>
                )}
              </div>
              <div className="coaching-synopsis-summary">{s.summary}</div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
