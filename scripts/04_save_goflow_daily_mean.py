# choose latest 24 hours of goflow files

import xarray as xr
import glob
import pandas as pd

file_path = '/home/mduplessis/share/EUMETSAT/processed_goflow_inputs/5E-25E_44S-33S/'
output_path = '/home/mduplessis/share/EUMETSAT/goflow_daily_means'

flist = sorted(glob.glob(f'{file_path}/*.nc'))[-50:]

if not flist:
    raise FileNotFoundError(f'No NetCDF files found in {file_path}')

ds = xr.open_mfdataset(flist, combine='nested', concat_dim='time', parallel=False)
ds = ds.sortby('time')
ds = ds.isel(time=~ds.indexes['time'].duplicated())

today_start = pd.Timestamp.utcnow().tz_localize(None).normalize()
tomorrow_start = today_start + pd.Timedelta(days=1)
yesterday_start = today_start - pd.Timedelta(days=1)

ds = ds.where((ds['time'] >= yesterday_start) & (ds['time'] < today_start), drop=True)

if ds.sizes.get('time', 0) == 0:
    raise ValueError(f'No data found for current UTC day: {today_start.date()}')

# convert from Kelvin to Celsius
ds['BT'] = ds['BT'] - 273.15  

# calculate the cloud fraction

start_time = pd.to_datetime(ds.time.min().values)
end_time = pd.to_datetime(ds.time.max().values)

cloud_count = (ds['mask'] == 0).sum(dim='time', skipna=True).load()
valid_count = ds['mask'].count(dim='time').load()
cloud_fraction = xr.where(valid_count > 0, cloud_count / valid_count, float('nan'))
cloud_fraction.name = 'cloud_fraction'
cloud_fraction.attrs.update({
    'long_name': 'Cloud fraction from mask occurrences',
    'units': '1',
    'description': 'Per-pixel fraction of times mask == 1 over available time samples',
    'start_time': start_time.isoformat(),
    'end_time': end_time.isoformat(),
})

ds[cloud_fraction.name] = cloud_fraction

ds['start_time'] = start_time
ds['end_time'] = end_time

ds['BT_masked'] = ds['BT'].where(ds['mask'] == 1) # Apply mask to BT

ds['BT_masked'] = ds['BT_masked'].max(dim='time') # Compute the maximum BT value over time for each pixel

start_stamp = start_time.strftime('%Y%m%d')

ds[['BT_masked', 'cloud_fraction', 'start_time', 'end_time']].to_netcdf(f'{output_path}/BT_masked_Meteosat_{start_stamp}.nc') # save to netcdf

print('Saved daily mean data to', f'{output_path}/BT_masked_Meteosat_{start_stamp}.nc')

ds[['BT_masked', 'cloud_fraction', 'start_time', 'end_time']]