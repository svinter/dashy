import React, { useState, useRef, useEffect } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

interface CommentCellProps {
  weekStart: string;   // YYYY-MM-DD (Monday)
  laneId: string;
  comment: string;
  cellBg: string;
  borderBottom?: string;
  borderTop?: string;
}

async function upsertComment(week_start: string, lane_id: string, comment: string) {
  const res = await fetch('/api/glance/comments', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ week_start, lane_id, comment }),
  });
  if (!res.ok) throw new Error('Failed to save comment');
  return res.json();
}

export function CommentCell({ weekStart, laneId, comment, cellBg, borderBottom, borderTop }: CommentCellProps) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editText, setEditText] = useState(comment);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: (text: string) => upsertComment(weekStart, laneId, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['glance-weeks'] });
    },
  });

  useEffect(() => {
    setEditText(comment);
  }, [comment]);

  useEffect(() => {
    if (expanded && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [expanded]);

  function open() {
    setEditText(comment);
    setExpanded(true);
  }

  function save() {
    mutation.mutate(editText);
    setExpanded(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { save(); return; }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); }
  }

  const tdStyle: React.CSSProperties = {
    background: cellBg,
    verticalAlign: 'middle',
    padding: '2px 6px',
    borderBottom,
    borderTop,
    cursor: expanded ? 'auto' : 'text',
  };

  if (expanded) {
    return (
      <td style={{ ...tdStyle, padding: '2px', verticalAlign: 'top' }}>
        <textarea
          ref={textareaRef}
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={save}
          style={{
            width: '100%',
            minHeight: '42px',
            resize: 'none',
            border: '1px solid rgba(0,0,0,0.15)',
            borderRadius: '2px',
            padding: '2px 4px',
            fontSize: '10px',
            fontFamily: 'inherit',
            background: cellBg,
            outline: 'none',
            lineHeight: 1.4,
            boxSizing: 'border-box',
          }}
        />
      </td>
    );
  }

  return (
    <td style={tdStyle} onClick={open}>
      {comment ? (
        <span
          style={{
            fontSize: '10px',
            color: 'var(--color-text-muted, #555)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            display: 'block',
          }}
          title={comment}
        >
          {comment}
          <span style={{ opacity: 0.4, marginLeft: '4px', fontSize: '9px' }}>↗</span>
        </span>
      ) : (
        <span
          style={{
            display: 'block',
            height: '100%',
            minHeight: '14px',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,0,0,0.03)'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
        />
      )}
    </td>
  );
}
