#!/usr/bin/env bash
# Train and test splits for both domains: separate simulation seeds (dev = 41), separate injection seeds (dev = 7).
# Run from track_2b: bash scripts/make_splits.sh  (resumable: rerun after an interruption)
set -u
PY=.venv/Scripts/python
export PYTHONIOENCODING=utf-8
LOG=results/scratch/splits
mkdir -p $LOG

sim() {  # domain split seed n; a partial run is resumed, never started over
    RESUME=$([ -f data/sim/$1-$2/progress.jsonl ] && echo --resume)
    $PY -m rosetta_flow.gen.simulate --domain $1 --n $4 --seed $3 --out data/sim/$1-$2 $RESUME \
        --workers 8 --max-tokens 6000000 >> $LOG/sim-$1-$2.log 2>&1
}
echo "== simulate"
sim refunds train 101 420 &
sim manufacturing train 101 420 &
sim refunds test 202 132 &
sim manufacturing test 202 132 &
wait
# a run that died at startup leaves no manifest: retry it alone
for spec in "refunds train 101 420" "manufacturing train 101 420" "refunds test 202 132" "manufacturing test 202 132"; do
    set -- $spec
    [ -f data/sim/$1-$2/manifest.json ] || { echo "retrying $1-$2"; sim $1 $2 $3 $4; }
done
for d in data/sim/*-train data/sim/*-test; do echo "$d: $(tail -1 $LOG/sim-$(basename $d).log | cut -c1-260)"; done

echo "== inject"
for D in refunds manufacturing; do
    for S in train test; do
        SEED=$([ $S = train ] && echo 11 || echo 13)
        rm -rf data/sets/$D-$S
        $PY -m rosetta_flow.gen.inject --sim data/sim/$D-$S --out data/sets/$D-$S --rate 0.5 --seed $SEED \
            > $LOG/inject-$D-$S.log 2>&1
        echo "$D-$S: $(tail -1 $LOG/inject-$D-$S.log | cut -c1-700)"
    done
done
