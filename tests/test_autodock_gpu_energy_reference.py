"""Independent formula controls, no GPU or docking required."""
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"validation"))
from autodock_gpu_energy_reference import intramolecular


class EnergyReferenceTests(unittest.TestCase):
    def meta(self):
        r=np.arange(1,2049)/100
        return {"pairs":[0,1],"atom_types":[0,0],"types":1,"AC":[1.],"BD":[0.],
            "opt_distance":[2.],"exponents":[12*256+6],"charges":[0.,0.],"solpar":[0.],
            "volume":[0.],"qasp":.01097,"spacing":1.,"smooth":.5,"elec_min":.01,
            "coeff_elec":1.,"coeff_desolv":1.,"r6":r**-6,"r10":r**-10,"r12":r**-12,
            "eps":np.zeros(2048),"desolv":np.zeros(2048)}

    def test_distance_quantization_separated_from_continuous(self):
        xyz=np.array([[[0.,0.,0.],[1.234,0.,0.]]])
        exact=intramolecular(xyz,self.meta(),"gpu_continuous")[0,0]
        table=intramolecular(xyz,self.meta(),"table")[0,0]
        self.assertAlmostEqual(exact,1.484**-12)
        self.assertAlmostEqual(table,1.48**-12)
        self.assertNotAlmostEqual(exact,table)

    def test_cutoffs_and_entity_inventory(self):
        xyz=np.array([[[0.,0.,0.],[30.,0.,0.]]]*205)
        result=intramolecular(xyz,self.meta(),"gpu_continuous")
        self.assertEqual(result.shape,(205,3))
        self.assertTrue(np.array_equal(result,np.zeros_like(result)))

    def test_gpu_dielectric_approximation_explicit(self):
        meta=self.meta()
        meta.update(AC=[0.],charges=[1.,-1.])
        xyz=np.array([[[0.,0.,0.],[3.1,0.,0.]]])
        result=intramolecular(xyz,meta,"gpu_continuous")
        self.assertAlmostEqual(result[0,1],-(1.10859/(3.1+1.26366)**2+.010358)/3.1)

    def test_native_cutoff_branch_separate_from_continuous_terms(self):
        meta=self.meta();meta.update(charges=[1.,-1.])
        xyz=np.array([[[0.,0.,0.],[8.-1e-7,0.,0.]]])
        original=intramolecular(xyz,meta,"gpu_continuous")
        conditioned=intramolecular(xyz,meta,"gpu_continuous",cutoff_distances=np.array([[8.]]))
        self.assertGreater(original[0,0],0)
        self.assertEqual(conditioned[0,0],0)
        self.assertEqual(original[0,1],conditioned[0,1])
        self.assertTrue(np.array_equal(original,intramolecular(xyz,meta,"gpu_continuous")))

    def test_native_electro_cutoff_uses_float32_constant(self):
        meta=self.meta();meta.update(charges=[1.,-1.])
        distance=float(np.float32(20.48))
        xyz=np.array([[[0.,0.,0.],[distance,0.,0.]]])
        self.assertLess(intramolecular(xyz,meta,"gpu_continuous")[0,1],0)
        self.assertEqual(intramolecular(xyz,meta,"gpu_continuous",cutoff_distances=np.array([[distance]]))[0,1],0)

    def test_cutoff_inventory_cannot_drop_states_or_pairs(self):
        xyz=np.array([[[0.,0.,0.],[3.,0.,0.]]])
        for distances in (np.zeros((0,1)),np.zeros((1,2)),np.array([[np.nan]]),np.array([[-1.]])):
            with self.assertRaises(ValueError):
                intramolecular(xyz,self.meta(),"gpu_continuous",cutoff_distances=distances)


if __name__=="__main__":
    unittest.main()
