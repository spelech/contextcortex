import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { AddRepoModal } from '../components/git/AddRepoModal';
import { RepoListTable } from '../components/git/RepoListTable';
import type { Repo } from '../types';

describe('Commit History Retention Frontend Controls', () => {
  it('renders retain commits input on AddRepoModal and calls setRetainCommitsCount', () => {
    const setRetain = vi.fn();
    render(
      <AddRepoModal
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        alias="test"
        setAlias={vi.fn()}
        url="https://github.com/org/test"
        setUrl={vi.fn()}
        branch="main"
        setBranch={vi.fn()}
        provider="github"
        setProvider={vi.fn()}
        authUser=""
        setAuthUser={vi.fn()}
        token=""
        setToken={vi.fn()}
        retainCommitsCount={20}
        setRetainCommitsCount={setRetain}
        isSaving={false}
      />
    );

    const input = screen.getByLabelText(/Retain Recent Commits Count/i) as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('20');

    fireEvent.change(input, { target: { value: '15' } });
    expect(setRetain).toHaveBeenCalledWith(15);
  });

  it('renders history retention badge on RepoListTable and prompts for edit', () => {
    const onUpdateRetain = vi.fn();
    vi.spyOn(window, 'prompt').mockReturnValue('30');

    const repos: Repo[] = [
      {
        id: 10,
        name: 'repo-with-history',
        url: 'https://github.com/org/repo',
        branch: 'main',
        status: 'synced',
        retain_commits_count: 25,
      },
      {
        id: 11,
        name: 'repo-no-history',
        url: 'https://github.com/org/no-history',
        branch: 'main',
        status: 'synced',
        retain_commits_count: 0,
      },
    ];

    render(
      <RepoListTable
        repos={repos}
        onSync={vi.fn()}
        onToggleAutoSync={vi.fn()}
        onUpdateRetainCommits={onUpdateRetain}
        onOpenWebhook={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getAllByText('25 commits')[0]).toBeInTheDocument();
    expect(screen.getAllByText('Disabled')[0]).toBeInTheDocument();

    const editBtn = screen.getAllByLabelText('Edit commit retention for repo-with-history')[0];
    fireEvent.click(editBtn);

    expect(window.prompt).toHaveBeenCalled();
    expect(onUpdateRetain).toHaveBeenCalledWith(10, 30);
  });
});
