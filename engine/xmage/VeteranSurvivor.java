// Patched copy of XMage 1.4.62 (tag xmage_1.4.62V1) Mage.Sets/src/mage/cards/v/VeteranSurvivor.java, MIT License,
// Copyright (c) 2010 betasteward@gmail.com. Compiled with our classes, which come first on the classpath, so it
// replaces the jar's copy. The only change is marked "PATCH (mtg-ai)" and is the fix XMage's master branch has: the
// static ability looked for "cards exiled with this" under its own zone change counter (0), while the Survival
// trigger exiles under the permanent's, so the +3/+3 and hexproof never turned on. See engine/xmage/README.md, "Our
// patches to XMage", and VeteranSurvivorCheck.java.
package mage.cards.v;

import mage.MageInt;
import mage.abilities.Ability;
import mage.abilities.abilityword.SurvivalAbility;
import mage.abilities.common.SimpleStaticAbility;
import mage.abilities.condition.Condition;
import mage.abilities.decorator.ConditionalContinuousEffect;
import mage.abilities.effects.common.ExileTargetForSourceEffect;
import mage.abilities.effects.common.continuous.BoostSourceEffect;
import mage.abilities.effects.common.continuous.GainAbilitySourceEffect;
import mage.abilities.keyword.HexproofAbility;
import mage.cards.CardImpl;
import mage.cards.CardSetInfo;
import mage.constants.CardType;
import mage.constants.Duration;
import mage.constants.SubType;
import mage.game.ExileZone;
import mage.game.Game;
import mage.target.common.TargetCardInGraveyard;
import mage.util.CardUtil;

import java.util.UUID;

/**
 * @author TheElk801
 */
public final class VeteranSurvivor extends CardImpl {

    public VeteranSurvivor(UUID ownerId, CardSetInfo setInfo) {
        super(ownerId, setInfo, new CardType[]{CardType.CREATURE}, "{W}");

        this.subtype.add(SubType.HUMAN);
        this.subtype.add(SubType.SURVIVOR);
        this.power = new MageInt(2);
        this.toughness = new MageInt(1);

        // Survival -- At the beginning of your second main phase, if Veteran Survivor is tapped, exile up to one target card from a graveyard.
        Ability ability = new SurvivalAbility(new ExileTargetForSourceEffect());
        ability.addTarget(new TargetCardInGraveyard(0, 1));
        this.addAbility(ability);

        // As long as there are three or more cards exiled with Veteran Survivor, it gets +3/+3 and has hexproof.
        ability = new SimpleStaticAbility(new ConditionalContinuousEffect(
                new BoostSourceEffect(3, 3, Duration.WhileOnBattlefield),
                VeteranSurvivorCondition.instance, "as long as there are three " +
                "or more cards exiled with {this}, it gets +3/+3"
        ));
        ability.addEffect(new ConditionalContinuousEffect(
                new GainAbilitySourceEffect(HexproofAbility.getInstance()),
                VeteranSurvivorCondition.instance, "and has hexproof"
        ));
        this.addAbility(ability);
    }

    private VeteranSurvivor(final VeteranSurvivor card) {
        super(card);
    }

    @Override
    public VeteranSurvivor copy() {
        return new VeteranSurvivor(this);
    }
}

enum VeteranSurvivorCondition implements Condition {
    instance;

    @Override
    public boolean apply(Game game, Ability source) {
        // PATCH (mtg-ai): was CardUtil.getExileZoneId(game, source)
        ExileZone exileZone = game.getExile().getExileZone(CardUtil.getExileZoneId(
                game, source.getSourceId(), game.getState().getZoneChangeCounter(source.getSourceId())));
        return exileZone != null && exileZone.getCards(game).size() >= 3;
    }
}
