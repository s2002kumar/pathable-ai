'use client';

import type { MobilityProfile, ProfileKey } from '@pathable/contracts';
import { Icon, type IconName } from '@/components/Icon';
import { cx } from '@/lib/cx';
import { type ProfilesState, profileRuleLines } from './mobility-profiles';
import styles from './Planner.module.css';

/**
 * The five profiles the routing service offers, by key, label and glyph.
 *
 * Five, not the Golden Master's four: the design drew a "Standard pedestrian"
 * option, but the shortest walking route is computed on every request and is
 * not a profile a traveller chooses — and it drew one option for walker and
 * cane where the API has two. The labels are the API's own display names; the
 * glyphs are the design's. What each profile rules out is read from
 * `/routes/profiles`, never restated here.
 */
export const PROFILE_OPTIONS: ReadonlyArray<{
  readonly key: Exclude<ProfileKey, 'custom'>;
  readonly label: string;
  readonly icon: IconName;
  readonly listIcon: IconName;
}> = [
  {
    key: 'wheelchair',
    label: 'Wheelchair',
    icon: 'profile-wheelchair',
    listIcon: 'profile-wheelchair-solid',
  },
  {
    key: 'walker',
    label: 'Walker or rollator',
    icon: 'profile-cane',
    listIcon: 'profile-cane-large',
  },
  {
    key: 'crutches',
    label: 'Crutches or cane',
    icon: 'profile-cane',
    listIcon: 'profile-cane-large',
  },
  {
    key: 'stroller',
    label: 'Stroller or pram',
    icon: 'profile-stroller',
    listIcon: 'profile-stroller',
  },
  {
    key: 'reduced_mobility',
    label: 'Reduced mobility',
    icon: 'profile-walking',
    listIcon: 'profile-walking',
  },
];

/** One short line for what a profile rules out, from its own definition. */
export function profileSummary(profile: MobilityProfile | undefined): string {
  if (profile === undefined) return 'Rules from the routing service';
  return profile.excludes_steps ? 'Avoids recorded stairways' : 'Stairs allowed, at a cost';
}

export type ProfileChooserProps = {
  readonly selected: ProfileKey;
  readonly onChange: (key: ProfileKey) => void;
  readonly profiles: ProfilesState;
  /** `list`: the planning form (17:3634). `grid`: beside a result (9:2065). */
  readonly variant: 'list' | 'grid';
  /** Replaces the selected option's rule line with a fact about its route. */
  readonly selectedNote?: string | null;
};

/**
 * The profiles as a radio group.
 *
 * Native radio buttons under each card: the arrow keys, the group's single tab
 * stop and the announcement are the platform's own. The full rules the
 * service states are always in the accessible description; the visible line is
 * the hard limit, and the uphill control below says what is only a preference.
 */
export function ProfileChooser({
  selected,
  onChange,
  profiles,
  variant,
  selectedNote = null,
}: ProfileChooserProps) {
  const lookup = (key: ProfileKey) =>
    profiles.status === 'ready' ? profiles.profiles.get(key) : undefined;
  const selectedProfile = lookup(selected);
  const rules = selectedProfile ? profileRuleLines(selectedProfile) : null;
  const ruleText = rules
    ? `${rules.hard}${rules.preferences ? ` ${rules.preferences}` : ''}`
    : profiles.status === 'unavailable'
      ? 'This profile’s rules could not be loaded. The routing service still applies them.'
      : 'Loading this profile’s rules…';

  return (
    <fieldset
      className={styles.profileGroup}
      data-testid="mobility-profile"
      aria-describedby="profile-rule-text"
    >
      <legend className={styles.profileGroupHead}>
        <span className={styles.caps}>Mobility profile</span>
        {variant === 'list' ? (
          <span className={styles.profileGroupNote}>Selected profile</span>
        ) : null}
      </legend>

      <div className={variant === 'list' ? styles.profileList : styles.profileGrid}>
        {PROFILE_OPTIONS.map((option) => {
          const isSelected = option.key === selected;
          const sub =
            isSelected && selectedNote !== null ? selectedNote : profileSummary(lookup(option.key));
          return (
            <label
              key={option.key}
              className={styles.profileOption}
              data-selected={isSelected}
              data-testid={`profile-${option.key}`}
            >
              <input
                type="radio"
                name="mobility-profile"
                value={option.key}
                checked={isSelected}
                onChange={() => onChange(option.key)}
              />
              {variant === 'list' ? (
                <>
                  <span className={styles.profileMain}>
                    <span className={styles.profileTile}>
                      <Icon name={option.listIcon} />
                    </span>
                    <span className={styles.profileText}>
                      <span className={styles.profileName}>
                        {option.label}
                        {isSelected ? <span className={styles.dot} aria-hidden="true" /> : null}
                      </span>
                      <span className={styles.profileSub}>{sub}</span>
                    </span>
                  </span>
                  <span className={styles.profileRadio} aria-hidden="true">
                    {isSelected ? <Icon name="check" size={14} /> : null}
                  </span>
                </>
              ) : (
                <>
                  <span className={styles.profileGridIcon}>
                    <Icon name={option.icon} size={18} />
                  </span>
                  <span className={styles.profileText}>
                    <span className={styles.profileGridName}>{option.label}</span>
                    <span className={cx(styles.profileGridSub)}>{sub}</span>
                  </span>
                </>
              )}
            </label>
          );
        })}
      </div>

      {/* Every rule the service states for the chosen profile, hard limits and
          preferences apart. Read by assistive technology with the group. */}
      <p className="visually-hidden" id="profile-rule-text" data-testid="profile-rule">
        {ruleText}
      </p>
    </fieldset>
  );
}
