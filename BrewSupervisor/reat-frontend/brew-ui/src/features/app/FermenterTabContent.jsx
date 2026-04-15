import { ParameterDBPage } from '../parameterdb/ParameterDBPage';
import { StorageManagerPage } from '../storage/StorageManagerPage';
import { ArchiveViewerPage } from '../archive/ArchiveViewerPage';
import { RuleEditorModal } from '../rules/RuleEditorModal';
import { RulesStudioPage } from '../rules/RulesStudioPage';
import { SystemStudioPage } from '../system/SystemStudioPage';
import { CustomLayoutTab } from './CustomLayoutTab';
import asleepBreweryIcon from '../../assets/brewery-asleep.svg';

export function FermenterTabContent({
  selected,
  activeTab,
  onSaveSharedWorkspaceLayouts,
  workspaceSaveLoading,
  scenarioProps,
  dataProps,
  controlProps,
  archiveProps,
  rulesProps,
  systemProps,
  customTabs,
  layoutEditMode,
  onRenameCustomTab,
  onDeleteCustomTab,
  onAddCustomWidget,
  onRemoveCustomWidget,
  onMoveCustomWidget,
  onResizeCustomWidget,
  onCreateCustomTab,
  globalView,
  setGlobalView,
  ruleEditorProps,
  archiveViewPayload,
  selectedArchiveName,
  archiveViewLoading,
  archiveViewError,
}) {
  if (!selected) {
    return (
      <div className="empty-fermenter-state">
        <div className="empty-fermenter-stack">
          <img className="empty-fermenter-icon" src={asleepBreweryIcon} alt="" aria-hidden="true" />
          <p className="empty-fermenter-title">The Brewery seems to be asleep</p>
        </div>
      </div>
    );
  }

  const activeCustomTab = Array.isArray(customTabs)
    ? (customTabs.find((tab) => tab?.id === activeTab) || customTabs[0] || null)
    : null;
  const closeToSystemStudio = () => setGlobalView('system-studio');

  return (
    <>
      {activeCustomTab ? (
        <CustomLayoutTab
          selected={selected}
          customTab={activeCustomTab}
          editMode={layoutEditMode}
          scenarioProps={scenarioProps}
          dataProps={dataProps}
          controlProps={controlProps}
          archiveProps={archiveProps}
          rulesProps={rulesProps}
          systemProps={systemProps}
          onRenameTab={onRenameCustomTab}
          onDeleteTab={onDeleteCustomTab}
          onAddWidget={onAddCustomWidget}
          onRemoveWidget={onRemoveCustomWidget}
          onMoveWidget={onMoveCustomWidget}
          onResizeWidget={onResizeCustomWidget}
          onCreateTab={onCreateCustomTab}
          onSaveToSupervisor={onSaveSharedWorkspaceLayouts}
          saveToSupervisorBusy={workspaceSaveLoading}
        />
      ) : null}

      {globalView === 'parameterdb' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            background: '#11161c',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <ParameterDBPage
            fermenterId={selected?.id || null}
            fermenterName={selected?.name || null}
            onClose={closeToSystemStudio}
          />
        </div>
      )}

      {globalView === 'storage-manager' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            background: '#11161c',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <StorageManagerPage
            fermenterId={selected?.id || null}
            fermenterName={selected?.name || null}
            onClose={closeToSystemStudio}
          />
        </div>
      )}

      {globalView === 'archive-viewer' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            background: '#11161c',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <ArchiveViewerPage
            key={`${selectedArchiveName}:${archiveViewPayload?.measurement?.member ?? ''}`}
            archiveName={selectedArchiveName}
            archiveViewPayload={archiveViewPayload}
            archiveViewLoading={archiveViewLoading}
            archiveViewError={archiveViewError}
            onClose={() => setGlobalView(null)}
          />
        </div>
      )}

      {globalView === 'rules-studio' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            background: '#11161c',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <RulesStudioPage
            fermenterId={selected?.id || null}
            fermenterName={selected?.name || null}
            rulesProps={rulesProps}
            onClose={closeToSystemStudio}
          />
        </div>
      )}

      {globalView === 'system-studio' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            background: '#11161c',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <SystemStudioPage
            fermenterId={selected?.id || null}
            fermenterName={selected?.name || null}
            systemProps={systemProps}
            onClose={() => setGlobalView(null)}
          />
        </div>
      )}

      <RuleEditorModal {...ruleEditorProps} />
    </>
  );
}
