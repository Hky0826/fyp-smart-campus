import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Edit3, Layers, Plus, Search, Shield, Trash2, UserPlus, X } from 'lucide-react';
import { cloudApi } from '../lib/cloudApi';
import { useToast } from '../providers/ToastProvider';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

export function RolesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get('tab') === 'groups' ? 'groups' : 'roles';
  const [activeTab, setActiveTab] = useState(initialTab);

  const queryClient = useQueryClient();
  const toast = useToast();

  // Role modal state
  const [roleModal, setRoleModal] = useState({ open: false, role: null });
  const [roleName, setRoleName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [savingRole, setSavingRole] = useState(false);
  const [deleteRoleTarget, setDeleteRoleTarget] = useState(null);

  // Access Group modal state
  const [groupModal, setGroupModal] = useState({ open: false, group: null });
  const [groupName, setGroupName] = useState('');
  const [groupDescription, setGroupDescription] = useState('');
  const [selectedRoleIds, setSelectedRoleIds] = useState([]);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [userQuery, setUserQuery] = useState('');
  const [savingGroup, setSavingGroup] = useState(false);
  const [deleteGroupTarget, setDeleteGroupTarget] = useState(null);

  const { data: roles = [], isLoading: loadingRoles } = useQuery({
    queryKey: ['roles'],
    queryFn: () => cloudApi.get('/api/iam/roles'),
  });

  const { data: groups = [], isLoading: loadingGroups } = useQuery({
    queryKey: ['access-groups'],
    queryFn: () => cloudApi.get('/api/iam/access-groups'),
  });

  const { data: userSearchRes } = useQuery({
    queryKey: ['user-picker', userQuery],
    queryFn: () =>
      cloudApi.get(`/api/iam/users/paginated?page=1&page_size=15&q=${encodeURIComponent(userQuery.trim())}`),
    enabled: groupModal.open,
    staleTime: 15_000,
  });

  const userCandidates = useMemo(() => {
    const items = userSearchRes?.items || [];
    const chosenIds = new Set(selectedUsers.map((u) => u.user_id));
    return items.filter((u) => !chosenIds.has(u.user_id));
  }, [userSearchRes, selectedUsers]);

  const switchTab = (tab) => {
    setActiveTab(tab);
    setSearchParams(tab === 'groups' ? { tab: 'groups' } : {}, { replace: true });
  };

  // --- Role Handlers ---
  const openRoleModal = (role = null) => {
    setRoleName(role?.role_name || '');
    setRoleDescription(role?.description || '');
    setRoleModal({ open: true, role });
  };

  const handleSaveRole = async (e) => {
    e.preventDefault();
    setSavingRole(true);
    try {
      if (roleModal.role) {
        await cloudApi.put(`/api/iam/roles/${roleModal.role.role_id}`, {
          role_name: roleName.trim(),
          description: roleDescription,
        });
        toast.success('Role updated.');
      } else {
        await cloudApi.post('/api/iam/roles', {
          role_name: roleName.trim(),
          description: roleDescription,
        });
        toast.success('Role created.');
      }
      queryClient.invalidateQueries({ queryKey: ['roles'] });
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
      setRoleModal({ open: false, role: null });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSavingRole(false);
    }
  };

  const handleDeleteRole = async () => {
    if (!deleteRoleTarget) return;
    try {
      await cloudApi.delete(`/api/iam/roles/${deleteRoleTarget.role_id}`);
      toast.success('Role deleted.');
      queryClient.invalidateQueries({ queryKey: ['roles'] });
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleteRoleTarget(null);
    }
  };

  // --- Access Group Handlers ---
  const openGroupModal = (group = null) => {
    setGroupName(group?.group_name || '');
    setGroupDescription(group?.description || '');
    setSelectedRoleIds((group?.roles || []).map((r) => r.role_id));
    setSelectedUsers(group?.users || []);
    setUserQuery('');
    setGroupModal({ open: true, group });
  };

  const toggleGroupRole = (roleId) => {
    setSelectedRoleIds((prev) =>
      prev.includes(roleId) ? prev.filter((id) => id !== roleId) : [...prev, roleId]
    );
  };

  const addUserToGroup = (user) => {
    setSelectedUsers((prev) => [
      ...prev,
      { user_id: user.user_id, full_name: user.full_name, email: user.email, is_active: user.is_active },
    ]);
  };

  const removeUserFromGroup = (userId) => {
    setSelectedUsers((prev) => prev.filter((u) => u.user_id !== userId));
  };

  const handleSaveGroup = async (e) => {
    e.preventDefault();
    setSavingGroup(true);
    try {
      const payload = {
        group_name: groupName.trim(),
        description: groupDescription.trim() || null,
        role_ids: selectedRoleIds,
        user_ids: selectedUsers.map((u) => u.user_id),
      };
      if (groupModal.group) {
        await cloudApi.put(`/api/iam/access-groups/${groupModal.group.group_id}`, payload);
        toast.success('Access group updated.');
      } else {
        await cloudApi.post('/api/iam/access-groups', payload);
        toast.success('Access group created.');
      }
      queryClient.invalidateQueries({ queryKey: ['access-groups'] });
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
      setGroupModal({ open: false, group: null });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSavingGroup(false);
    }
  };

  const handleDeleteGroup = async () => {
    if (!deleteGroupTarget) return;
    try {
      await cloudApi.delete(`/api/iam/access-groups/${deleteGroupTarget.group_id}`);
      toast.success('Access group deleted.');
      queryClient.invalidateQueries({ queryKey: ['access-groups'] });
      queryClient.invalidateQueries({ queryKey: ['rbac-matrix'] });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setDeleteGroupTarget(null);
    }
  };

  const roleColumns = useMemo(
    () => [
      {
        id: 'id',
        header: 'ID',
        cell: ({ row }) => <span className="font-mono text-xs text-slate-500">#{row.original.role_id}</span>,
      },
      {
        id: 'name',
        header: 'Role Name',
        cell: ({ row }) => <StatusBadge variant="info">{row.original.role_name}</StatusBadge>,
      },
      {
        id: 'desc',
        header: 'Description',
        cell: ({ row }) => <span className="text-sm text-slate-600 dark:text-slate-400">{row.original.description || '—'}</span>,
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <button
              type="button"
              onClick={() => openRoleModal(row.original)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <Edit3 className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setDeleteRoleTarget(row.original)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ),
      },
    ],
    []
  );

  const groupColumns = useMemo(
    () => [
      {
        id: 'group_name',
        header: 'Access Group',
        cell: ({ row }) => (
          <div>
            <div className="font-bold text-slate-900 dark:text-slate-100">{row.original.group_name}</div>
            {row.original.description && (
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{row.original.description}</div>
            )}
          </div>
        ),
      },
      {
        id: 'roles',
        header: 'Included Roles',
        cell: ({ row }) => {
          const rList = row.original.roles || [];
          if (rList.length === 0) return <span className="text-xs text-slate-400">No roles</span>;
          return (
            <div className="flex flex-wrap gap-1">
              {rList.map((r) => (
                <StatusBadge key={r.role_id} variant="info">
                  {r.role_name}
                </StatusBadge>
              ))}
            </div>
          );
        },
      },
      {
        id: 'users',
        header: 'Individual Users',
        cell: ({ row }) => {
          const uList = row.original.users || [];
          if (uList.length === 0) return <span className="text-xs text-slate-400">No individual users</span>;
          const preview = uList.slice(0, 2);
          const remaining = uList.length - preview.length;
          return (
            <div className="flex flex-wrap items-center gap-1">
              {preview.map((u) => (
                <span
                  key={u.user_id}
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                >
                  {u.full_name}
                </span>
              ))}
              {remaining > 0 && (
                <span className="text-[11px] font-semibold text-slate-500">+{remaining} more</span>
              )}
            </div>
          );
        },
      },
      {
        id: 'usage',
        header: 'Assigned To',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-slate-500">
            {row.original.node_count} room{row.original.node_count === 1 ? '' : 's'} · {row.original.device_count} device{row.original.device_count === 1 ? '' : 's'}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        meta: { align: 'right' },
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <button
              type="button"
              onClick={() => openGroupModal(row.original)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <Edit3 className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setDeleteGroupTarget(row.original)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Access Roles & Groups
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Define roles and bundle multiple roles or individual users into reusable access groups for rooms and devices.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1">
            <button
              type="button"
              onClick={() => switchTab('roles')}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${
                activeTab === 'roles'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              <Shield className="w-3.5 h-3.5" /> Roles ({roles.length})
            </button>
            <button
              type="button"
              onClick={() => switchTab('groups')}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${
                activeTab === 'groups'
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
              }`}
            >
              <Layers className="w-3.5 h-3.5" /> Access Groups ({groups.length})
            </button>
          </div>

          {activeTab === 'roles' ? (
            <button
              type="button"
              onClick={() => openRoleModal(null)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              <Plus className="w-4 h-4" /> Add Role
            </button>
          ) : (
            <button
              type="button"
              onClick={() => openGroupModal(null)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              <Plus className="w-4 h-4" /> Create Group
            </button>
          )}
        </div>
      </div>

      {activeTab === 'roles' ? (
        <DataTable columns={roleColumns} data={roles} loading={loadingRoles} total={roles.length} />
      ) : (
        <DataTable columns={groupColumns} data={groups} loading={loadingGroups} total={groups.length} />
      )}

      {/* Role Create / Edit Modal */}
      {roleModal.open && (
        <div
          className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => setRoleModal({ open: false, role: null })}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                {roleModal.role ? 'Edit Role' : 'Create Role'}
              </h3>
              <button
                type="button"
                onClick={() => setRoleModal({ open: false, role: null })}
                className="p-1 text-slate-400"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleSaveRole} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Role Name *</label>
                <input
                  type="text"
                  required
                  value={roleName}
                  onChange={(e) => setRoleName(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Description</label>
                <textarea
                  rows={3}
                  value={roleDescription}
                  onChange={(e) => setRoleDescription(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setRoleModal({ open: false, role: null })}
                  className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 dark:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingRole}
                  className="px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white"
                >
                  {savingRole ? 'Saving...' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Access Group Create / Edit Modal */}
      {groupModal.open && (
        <div
          className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-900/50 p-4"
          onClick={() => setGroupModal({ open: false, group: null })}
        >
          <div
            className="w-full max-w-xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                {groupModal.group ? 'Edit Access Group' : 'Create Access Group'}
              </h3>
              <button
                type="button"
                onClick={() => setGroupModal({ open: false, group: null })}
                className="p-1 text-slate-400"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleSaveGroup} className="space-y-5">
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Group Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g., Campus Public, Staff & Faculty, Server Room Team"
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-1">Description</label>
                <textarea
                  rows={2}
                  placeholder="Optional description of who this group grants access to"
                  value={groupDescription}
                  onChange={(e) => setGroupDescription(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm"
                />
              </div>

              {/* Roles Picker */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-bold uppercase text-slate-500">
                    Included Roles ({selectedRoleIds.length})
                  </label>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setSelectedRoleIds(roles.map((r) => r.role_id))}
                      className="text-[11px] font-semibold text-indigo-600 hover:underline"
                    >
                      Select All
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedRoleIds([])}
                      className="text-[11px] font-semibold text-slate-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/60">
                  {roles.map((r) => {
                    const checked = selectedRoleIds.includes(r.role_id);
                    return (
                      <button
                        key={r.role_id}
                        type="button"
                        onClick={() => toggleGroupRole(r.role_id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors ${
                          checked
                            ? 'bg-indigo-600 text-white border-indigo-600'
                            : 'bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-indigo-400'
                        }`}
                      >
                        {r.role_name}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Individual Users Picker */}
              <div>
                <label className="block text-xs font-bold uppercase text-slate-500 mb-2">
                  Individual Users ({selectedUsers.length})
                </label>

                {selectedUsers.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2.5">
                    {selectedUsers.map((u) => (
                      <span
                        key={u.user_id}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30"
                      >
                        <span>{u.full_name}</span>
                        <span className="text-[10px] opacity-70 font-mono">({u.email})</span>
                        <button
                          type="button"
                          onClick={() => removeUserFromGroup(u.user_id)}
                          className="hover:text-red-600"
                          aria-label={`Remove ${u.full_name}`}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                <div className="relative">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={userQuery}
                    onChange={(e) => setUserQuery(e.target.value)}
                    placeholder="Search users by name or email to add..."
                    className="w-full pl-9 pr-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm"
                  />
                </div>

                <div className="mt-2 max-h-40 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
                  {userCandidates.length === 0 ? (
                    <div className="p-3 text-xs text-slate-400 text-center">
                      {userQuery.trim() ? 'No matching users found.' : 'All loaded users are already added.'}
                    </div>
                  ) : (
                    userCandidates.map((u) => (
                      <button
                        key={u.user_id}
                        type="button"
                        onClick={() => addUserToGroup(u)}
                        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                      >
                        <div>
                          <div className="text-xs font-bold text-slate-900 dark:text-slate-100">{u.full_name}</div>
                          <div className="text-[11px] font-mono text-slate-500">{u.email}</div>
                        </div>
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                          <UserPlus className="w-3.5 h-3.5" /> Add
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setGroupModal({ open: false, group: null })}
                  className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 dark:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingGroup}
                  className="px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white"
                >
                  {savingGroup ? 'Saving...' : 'Save Group'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteRoleTarget)}
        title="Delete Role"
        message={`Delete role "${deleteRoleTarget?.role_name}"? Roles assigned to active users cannot be deleted.`}
        confirmLabel="Delete"
        onConfirm={handleDeleteRole}
        onCancel={() => setDeleteRoleTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteGroupTarget)}
        title="Delete Access Group"
        message={`Delete access group "${deleteGroupTarget?.group_name}"? It will be unassigned from ${deleteGroupTarget?.node_count || 0} room(s) and ${deleteGroupTarget?.device_count || 0} device(s).`}
        confirmLabel="Delete"
        onConfirm={handleDeleteGroup}
        onCancel={() => setDeleteGroupTarget(null)}
      />
    </div>
  );
}
