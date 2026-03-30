import { ParameterDBPage } from '../parameterdb/ParameterDBPage';
import { RuleEditorModal } from '../rules/RuleEditorModal';
import { ArchiveTabContainer } from './containers/ArchiveTabContainer';
import { ControlUiTabContainer } from './containers/ControlUiTabContainer';
import { DataTabContainer } from './containers/DataTabContainer';
import { RulesTabContainer } from './containers/RulesTabContainer';
import { ScheduleTabContainer } from './containers/ScheduleTabContainer';
import { SystemTabContainer } from './containers/SystemTabContainer';
import asleepBreweryIcon from '../../assets/brewery-asleep.svg';

export function FermenterTabContent({
  selected,
  activeTab,
  scheduleProps,
  dataProps,
  controlProps,
  archiveProps,
  rulesProps,
  systemProps,
  globalView,
  setGlobalView,
  ruleEditorProps,
}) {
  if (!selected) {
    return (
      <div className="empty-fermenter-state">
        <img className="empty-fermenter-icon" src={asleepBreweryIcon} alt="" aria-hidden="true" />
        <p className="empty-fermenter-title">The Brewery seems to be asleep</p>
      </div>
    );
  }

  return (
    <>
      {activeTab === 'schedule' ? (
        <ScheduleTabContainer {...scheduleProps} />
      ) : activeTab === 'control' ? (
        <ControlUiTabContainer {...controlProps} />
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
