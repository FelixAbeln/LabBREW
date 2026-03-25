import { ParameterDBPage } from '../parameterdb/ParameterDBPage';
import { RuleEditorModal } from '../rules/RuleEditorModal';
import { ArchiveTabContainer } from './containers/ArchiveTabContainer';
import { DataTabContainer } from './containers/DataTabContainer';
import { RulesTabContainer } from './containers/RulesTabContainer';
import { ScheduleTabContainer } from './containers/ScheduleTabContainer';
import { SystemTabContainer } from './containers/SystemTabContainer';

export function FermenterTabContent({
  selected,
  activeTab,
  scheduleProps,
  dataProps,
  archiveProps,
  rulesProps,
  systemProps,
  globalView,
  setGlobalView,
  ruleEditorProps,
}) {
  if (!selected) {
    return <p className="muted">Select a fermenter.</p>;
  }

  return (
    <>
      {activeTab === 'schedule' ? (
        <ScheduleTabContainer {...scheduleProps} />
      ) : activeTab === 'data' ? (
        <DataTabContainer {...dataProps} />
      ) : activeTab === 'archive' ? (
        <ArchiveTabContainer {...archiveProps} />
      ) : activeTab === 'rules' ? (
        <RulesTabContainer {...rulesProps} />
      ) : (
        <SystemTabContainer {...systemProps} />
      )}

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
            onClose={() => setGlobalView(null)}
          />
        </div>
      )}

      <RuleEditorModal {...ruleEditorProps} />
    </>
  );
}
