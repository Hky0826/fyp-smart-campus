import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';

export function SpeechConfigPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [subTab, setSubTab] = useState('phrases');
  const [phrase, setPhrase] = useState('');
  const [category, setCategory] = useState('campus');
  const [description, setDescription] = useState('');

  const { data: phrases = [], isLoading: loadingPhrases } = useQuery({
    queryKey: ['adaptation-phrases'],
    queryFn: () => cloudApi.get('/api/rag/adaptation-phrases'),
  });

  const { data: languages = [], isLoading: loadingLangs } = useQuery({
    queryKey: ['speech-languages'],
    queryFn: () => cloudApi.get('/api/rag/speech-languages'),
  });

  const addPhrase = async (e) => {
    e.preventDefault();
    if (!phrase.trim()) return;
    try {
      await cloudApi.post('/api/rag/adaptation-phrases', {
        phrase: phrase.trim(),
        category,
        description: description.trim() || null,
        is_active: true,
      });
      toast.success('Phrase added.');
      setPhrase('');
      setDescription('');
      queryClient.invalidateQueries({ queryKey: ['adaptation-phrases'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const toggleLanguage = async (code, action) => {
    try {
      await cloudApi.post(`/api/rag/speech-languages/${code}/${action}`, {});
      toast.success('Language updated.');
      queryClient.invalidateQueries({ queryKey: ['speech-languages'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const deletePhrase = async (id) => {
    try {
      await cloudApi.delete(`/api/rag/adaptation-phrases/${id}`);
      toast.success('Phrase removed.');
      queryClient.invalidateQueries({ queryKey: ['adaptation-phrases'] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const phraseCols = useMemo(
    () => [
      { id: 'phrase', header: 'Phrase / Acronym', cell: ({ row }) => <span className="font-bold">{row.original.phrase}</span> },
      { id: 'cat', header: 'Category', cell: ({ row }) => <StatusBadge variant="info">{row.original.category}</StatusBadge> },
      { id: 'desc', header: 'Notes / Translations', cell: ({ row }) => <span className="text-xs text-slate-500">{row.original.description || '—'}</span> },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) => (
          <button type="button" onClick={() => deletePhrase(row.original.phrase_id)} className="p-1.5 rounded-lg text-slate-500 hover:text-red-600">
            <Trash2 className="w-4 h-4" />
          </button>
        ),
      },
    ],
    []
  );

  const langCols = useMemo(
    () => [
      { id: 'code', header: 'Code', cell: ({ row }) => <span className="font-mono font-bold text-xs">{row.original.language_code}</span> },
      { id: 'name', header: 'Language', cell: ({ row }) => <span className="font-semibold">{row.original.language_name}</span> },
      {
        id: 'default',
        header: 'Default',
        cell: ({ row }) => (
          <button type="button" onClick={() => toggleLanguage(row.original.language_code, 'toggle-default')}>
            <StatusBadge variant={row.original.is_default ? 'info' : 'neutral'}>
              {row.original.is_default ? 'Default' : 'Optional'}
            </StatusBadge>
          </button>
        ),
      },
      {
        id: 'active',
        header: 'Active',
        cell: ({ row }) => (
          <button type="button" onClick={() => toggleLanguage(row.original.language_code, 'toggle-active')}>
            <StatusBadge variant={row.original.is_active ? 'success' : 'neutral'} dot>
              {row.original.is_active ? 'Active' : 'Disabled'}
            </StatusBadge>
          </button>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">Speech & Acronyms</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Configure STT adaptation vocabulary and supported kiosk voice languages.
          </p>
        </div>
        <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1">
          <button
            type="button"
            onClick={() => setSubTab('phrases')}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold ${subTab === 'phrases' ? 'bg-indigo-600 text-white' : 'text-slate-500'}`}
          >
            Acronyms & Phrases ({phrases.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab('languages')}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-bold ${subTab === 'languages' ? 'bg-indigo-600 text-white' : 'text-slate-500'}`}
          >
            Languages ({languages.length})
          </button>
        </div>
      </div>

      {subTab === 'phrases' && (
        <>
          <form onSubmit={addPhrase} className="flex flex-wrap gap-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-4">
            <input
              type="text"
              required
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder="New phrase or acronym (e.g. QIU)"
              className="flex-1 min-w-[180px] rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm"
            />
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Category"
              className="w-36 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm"
            />
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description / meaning"
              className="flex-1 min-w-[200px] rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm"
            />
            <button type="submit" className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 text-white">
              <Plus className="w-4 h-4" /> Add
            </button>
          </form>
          <DataTable columns={phraseCols} data={phrases} loading={loadingPhrases} total={phrases.length} />
        </>
      )}

      {subTab === 'languages' && (
        <DataTable columns={langCols} data={languages} loading={loadingLangs} total={languages.length} />
      )}
    </div>
  );
}
