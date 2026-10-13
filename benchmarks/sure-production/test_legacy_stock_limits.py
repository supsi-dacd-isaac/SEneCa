"""Overdraw, empty pools and paired-transfer conservation in the model equations."""
import ast
import re
from pathlib import Path
import unittest

import numpy as np
import xarray as xr

from legacy_stock_limits import D6, PV, RENOVATIONS, REQUESTED, equations, identifier, python_source, vensim_source


class StockLimitsTests(unittest.TestCase):
    def synthetic(self, stock, *, renovation=300., demolition=100., pv=200.):
        # Execute the actual generated expressions against a labelled synthetic
        # model with two heating technologies and both PV/battery categories.
        c = dict(zip(D6,[['A'],['HeatPump','Oil'],['VeryLow','Low','Moderate','High','VeryHigh'],['SFH'],['PVyes','PVno'],['Byes','Bno']]))
        s = xr.DataArray(stock,dims=D6,coords=c)
        coarse = s.sum(dim=['HS','PVpanel','Battery'])
        base = coarse.sel(Performance='VeryLow',drop=True)
        env = {'np':np,'xr':xr,'heating_solution':lambda:s,'time_step':lambda:1.,
               'equivalent_lifetime':lambda:xr.DataArray([1.,2.],dims=['HS'],coords={'HS':c['HS']})}
        helper = next(n for n in ast.parse(python_source((Path(__file__).parents[2]/'Vensim/SURE_pysd_v4.py').read_text())).body
                      if isinstance(n,ast.FunctionDef) and n.name=='_sure_flow_limit')
        exec(compile(ast.Module(body=[helper],type_ignores=[]),'stock helper','exec'),env)
        for perf in c['Performance']:
            env['res_'+perf.lower()+'_buildings'] = lambda p=perf:coarse.sel(Performance=p,drop=True)
        env['requested_res_verylow_demolition'] = lambda:xr.full_like(base,demolition)
        for perf,names in RENOVATIONS.items():
            for j,name in enumerate(names):
                env['requested_'+identifier(name)] = lambda p=perf,k=j:xr.full_like(base,renovation if p=='VeryLow' and k==0 else 0.)
        for j,name in enumerate(PV):
            env['requested_'+identifier(name)] = lambda k=j:xr.full_like(s.sel(PVpanel='PVno',Battery='Bno',drop=True),pv if k==0 else -20.)
        for eq in equations():
            code=f'def {identifier(eq.name)}():\n'+'\n'.join('    '+line for line in eq.python.splitlines())
            exec(code,env)

        def renovation_out():
            value=xr.zeros_like(s)
            shares=env['share_hs_by_archetype']()
            for perf,names in RENOVATIONS.items():
                total=sum(env[identifier(n)]() for n in names)
                value.loc[dict(Performance=perf)]=(shares.sel(Performance=perf,drop=True)*total).transpose('District','HS','Type','PVpanel','Battery')
            return value
        env['buildings_hs_renovation_from']=renovation_out
        demo=env['building_demolition_by_archetype']()
        reno=renovation_out()
        old=env['consumers_leaving_hs_for_old_age']()
        pvs=sum(env[identifier(n)]() for n in PV)
        pvout=xr.zeros_like(s)
        pvout.loc[dict(PVpanel='PVno',Battery='Bno')]=pvs
        out=demo+reno+old+pvout
        self.assertTrue(np.isfinite(out).all())
        self.assertTrue((out>=0).all())
        self.assertLessEqual(float((out-s).max()),1e-12)
        self.assertEqual(float(demo.sel(PVpanel='PVyes').sum()),0.)
        self.assertLessEqual(float(pvout.sum()),float(s.sel(PVpanel='PVno',Battery='Bno').sum())+1e-12)
        for n in PV:self.assertTrue((env[identifier(n)]()>=0).all())
        # Route each admitted transfer to its matching destination. Population
        # changes only by the admitted external demolition flow.
        incoming=xr.zeros_like(s)
        incoming.loc[dict(Performance='Low')]=reno.sel(Performance='VeryLow',drop=True)
        incoming += old.sum('HS')/2
        incoming.loc[dict(PVpanel='PVyes',Battery='Byes')] += (pvs*.3)
        incoming.loc[dict(PVpanel='PVyes',Battery='Bno')] += (pvs*.7)
        after=s+incoming-out
        self.assertGreaterEqual(float(after.min()),-1e-12)
        self.assertAlmostEqual(float(after.sum()),float(s.sum()-demo.sum()),places=11)
        return env

    def test_competing_transfers_cannot_overdraw_the_source(self):
        values=np.zeros((1,2,5,1,2,2))
        values[0,:,0,0,1,1]=[100.,30.]
        values[0,:,0,0,0,0]=[80.,20.]
        self.synthetic(values)

    def test_empty_demolition_pool_does_not_block_eligible_renovation(self):
        values=np.zeros((1,2,5,1,2,2))
        values[0,:,0,0,0,0]=[80.,20.]
        self.synthetic(values,renovation=20.)

    def test_empty_stocks_and_negative_demands_stay_finite_and_empty(self):
        self.synthetic(np.zeros((1,2,5,1,2,2)),renovation=-20.,demolition=-10.,pv=-3.)

    def test_vanishing_eligible_pool_does_not_change_other_renovations(self):
        # A 1e-17 residual in a depleted PVno category must not alter a
        # macroscopic renovation of PVyes buildings in the same archetype.
        for residual in (0.,1e-17,1e-8):
            values=np.zeros((1,2,5,1,2,2))
            values[0,:,0,0,0,0]=[80.,20.]
            values[0,0,0,0,1,1]=residual
            env=self.synthetic(values,renovation=20.)
            self.assertAlmostEqual(float(env['res_verylow_low_renovation']().sum()),20.,places=12)

    def test_requested_multi_clause_definitions_are_preserved(self):
        root=Path(__file__).parents[2]
        source=(root/'Vensim/SURE_pysd_v4.mdl').read_text(encoding='latin-1')
        generated=vensim_source(source)
        marker='\\\\\\---///'
        self.assertEqual(source.partition(marker)[2],generated.partition(marker)[2])
        # The real parser must see every new equation before the sketch.
        import tempfile
        from pysd.translators.vensim.vensim_file import VensimFile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'corrected.mdl'
            path.write_text(generated,encoding='latin-1')
            parsed=VensimFile(path,encoding='latin-1')
            parsed.parse()
            names={e.name for s in parsed.get_abstract_model().sections for e in s.elements}
            self.assertTrue({e.name for e in equations()} <= names)
            self.assertTrue({'Requested '+n for n in REQUESTED} <= names)
        # Compare complete defining clauses, including selectors and EXCEPT;
        # references to the same name inside other equations are irrelevant.
        for name in REQUESTED:
            pattern = re.compile(r'^\s*'+re.escape(name)+r'\s*(?:\[|=)')
            original = [b.strip() for b in source.split('|') if pattern.match(b)]
            requested = [b.strip().replace('Requested '+name,name,1)
                         for b in generated.split('|') if re.match(r'^\s*Requested '+re.escape(name)+r'\s*(?:\[|=)',b)]
            self.assertTrue(original,name)
            self.assertEqual(original,requested,name)
        self.assertIn('Building demolition by archetype[District,HS,VeryLow,Type,PVno,Bno]',generated)


class PhysicalGateTests(unittest.TestCase):
    def arrays(self):
        from sure_julia.physical import OUTPUTS
        a={n:np.zeros((40,1,2,1,1,2,2)) for n in OUTPUTS}
        a['Heating Solution'][:]=10.
        a['Annual archetypes']=a['Heating Solution'].sum(axis=6)
        a['Total Res buildings']=a['Heating Solution'].sum(axis=(2,5,6))
        return a

    def test_unchanged_population_and_fixed_input_offset_pass(self):
        from sure_julia.physical import check
        a=self.arrays()
        a['Total Res buildings']+=.001
        self.assertTrue(check(a)['pass'])

    def test_missing_nonfinite_and_negative_states_fail(self):
        from sure_julia.physical import check
        a=self.arrays()
        del a['Annual archetypes']
        self.assertFalse(check(a)['pass'])
        for value in (np.nan,-1.):
            a=self.arrays()
            a['Heating Solution'][10,0,0,0,0,0,0]=value
            self.assertFalse(check(a)['pass'])

    def test_unpaired_transfer_and_drifting_population_fail(self):
        from sure_julia.physical import check
        for source,gate in [('Consumers leaving HS for old age','heating_transfer'),
                            ('Buildings HS Renovation From','renovation_transfer'),
                            ('Consumers adopting PV no','pv_transfer')]:
            a=self.arrays()
            a[source][10,0,0,0,0,0,0]=1.
            self.assertFalse(check(a)['checks'][gate]['pass'])
        a=self.arrays()
        a['Total Res buildings'][10:]+=1.
        self.assertFalse(check(a)['checks']['fine_coarse_changes']['pass'])


if __name__=='__main__':unittest.main()
